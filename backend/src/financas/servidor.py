"""Servidor pessoal: consultas em Parquet, personalizações validadas no DuckDB.

Só consulta a Pluggy na ação explícita de atualizar faturas. Conexões curtas permitem usar a CLI entre requisições;
gravações concorrentes recebem conflito explícito e nunca são repetidas.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit

import duckdb

from financas.config import Configuracao, raiz_do_projeto
from financas.faturas import coletar_faturas
from financas.persistencia import Banco
from financas.pluggy import criar_cliente
from financas.personalizacoes import ConflitoDeRevisao, aplicar_ajuste, obter_catalogo, prever_regra
from financas.publicacao import ErroDePublicacao, publicar, serializar_json
from financas.views import aplicar_views

registrador = logging.getLogger(__name__)


class Conflito(Exception):
    """Outra aba ou processo está modificando os dados."""


class ServicoLocal:
    def __init__(self, config: Configuracao, frontend: Path, destino: Path | None = None):
        self.config = config
        self.frontend = frontend.resolve()
        self.destino = (destino or frontend / "dados").resolve()
        self.trava = Lock()
        self.token = secrets.token_urlsafe(32)
        self.revisao = 0
        self.pendente = False
        self.versao = ""

    @contextmanager
    def banco(self):
        if not self.trava.acquire(blocking=False):
            raise Conflito("O banco está em atualização. Aguarde e atualize a tela antes de tentar novamente.")
        try:
            try:
                with Banco.abrir(self.config.caminho_banco) as banco:
                    yield banco
            except duckdb.IOException as erro:
                raise Conflito("O banco está ocupado por outro processo. Termine a ingestão e tente novamente.") from erro
        finally:
            self.trava.release()

    def preparar(self):
        with self.banco() as banco:
            banco.criar_schema()
            banco.gravar_regras(self.config.regras)
            aplicar_views(banco, raiz_do_projeto() / "sql")
            self.revisao = banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
            try:
                self.versao = publicar(banco, self.destino).versao
            except ErroDePublicacao:
                if not (self.destino / "manifesto.json").is_file():
                    raise
                self.pendente = True
                registrador.warning("A publicação falhou; servindo a última versão válida.")

    def estado(self):
        return {"edicao": True, "token": self.token, "revisao": self.revisao,
                "versao": self.versao, "publicacao_pendente": self.pendente,
                "fonte": self.config.modo}

    def atualizar_estado(self):
        with self.banco() as banco:
            self.revisao = banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
            manifesto = json.loads((self.destino / "manifesto.json").read_text(encoding="utf-8"))
            self.versao = manifesto.get("versao", "")
            self.pendente = self.pendente or manifesto.get("revisao", -1) < self.revisao
            return self.estado()

    def catalogo(self):
        with self.banco() as banco:
            self.revisao = banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
            return {**obter_catalogo(banco), "revisao": self.revisao}

    def previa(self, regra):
        with self.banco() as banco:
            return prever_regra(banco, regra)

    def sincronizar_faturas(self, revisao):
        """Consulta somente cartões conhecidos, sob a mesma trava das edições."""
        with self.banco() as banco:
            self.revisao = banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
            if str(revisao) != str(self.revisao):
                raise Conflito("Os dados mudaram. Atualize a tela antes de consultar as faturas.")
            with criar_cliente(self.config) as cliente:
                resumo = coletar_faturas(cliente, banco, self.config.regras, hoje=date.today())
            aplicar_views(banco, raiz_do_projeto() / "sql")
            self.revisao = banco.conexao.execute(
                "UPDATE usr_estado SET revisao=revisao+1 WHERE id=1 RETURNING revisao"
            ).fetchone()[0]
            resultado = asdict(resumo)
            try:
                self.versao = publicar(banco, self.destino).versao
                self.pendente = False
            except ErroDePublicacao:
                self.pendente = True
                return 202, {**resultado, **self.estado(), "salvo": True, "publicado": False,
                             "aviso": "Consulta salva; publicação pendente. Use Publicar novamente."}
            return 200, {**resultado, **self.estado(), "salvo": True, "publicado": True}

    def gravar(self, ajuste, revisao, *, republicar=False):
        with self.banco() as banco:
            self.revisao = banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
            if str(revisao) != str(self.revisao):
                raise Conflito("Outra aba alterou os dados. Atualize a tela para revisar as mudanças antes de salvar.")
            try:
                resultado = {} if republicar else aplicar_ajuste(banco, ajuste, revisao_esperada=revisao)
            except ConflitoDeRevisao as erro:
                raise Conflito(str(erro)) from erro
            self.revisao = resultado.get("revisao", self.revisao)
            try:
                self.versao = publicar(banco, self.destino).versao
                self.pendente = False
            except ErroDePublicacao as erro:
                self.pendente = True
                return 202, {**resultado, **self.estado(), "salvo": True, "publicado": False,
                             "aviso": "A correção foi salva, mas a tela ainda mostra a versão anterior. Tente publicar novamente.",
                             "erro": str(erro)}
            return 200, {**resultado, **self.estado(), "salvo": True, "publicado": True}


def criar_servidor(servico: ServicoLocal, porta: int = 8000) -> ThreadingHTTPServer:
    class Manipulador(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "application/javascript", ".parquet": "application/octet-stream"}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(servico.frontend), **kwargs)

        def log_message(self, formato, *args):
            registrador.debug(formato, *args)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store" if not "/versoes/" in self.path else "private, max-age=31536000, immutable")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            if getattr(self, "_aceita_intervalos", False):
                self.send_header("Accept-Ranges", "bytes")
            super().end_headers()

        def send_head(self):
            self._intervalo_restante = None
            self._aceita_intervalos = False
            caminho = urlsplit(self.path).path
            if not caminho.lower().endswith(".parquet"):
                return super().send_head()
            arquivo = Path(self.translate_path(self.path))
            if not arquivo.is_file():
                return super().send_head()
            self._aceita_intervalos = True
            faixa = self.headers.get("Range")
            if not faixa or self.headers.get("If-Range"):
                return super().send_head()

            with arquivo.open("rb") as fonte:
                tamanho = os.fstat(fonte.fileno()).st_size
            partes = re.fullmatch(r"bytes=(\d*)-(\d*)", faixa.strip())
            inicio = fim = None
            if partes and (partes[1] or partes[2]) and max(len(partes[1]), len(partes[2])) <= 20 and tamanho:
                if partes[1]:
                    inicio = int(partes[1])
                    fim = min(int(partes[2]), tamanho - 1) if partes[2] else tamanho - 1
                else:
                    sufixo = int(partes[2])
                    if sufixo:
                        inicio = max(tamanho - sufixo, 0)
                        fim = tamanho - 1
            if inicio is None or inicio >= tamanho or fim < inicio:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{tamanho}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None

            fonte = arquivo.open("rb")
            fonte.seek(inicio)
            self._intervalo_restante = fim - inicio + 1
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(str(arquivo)))
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
            self.send_header("Content-Length", str(self._intervalo_restante))
            self.send_header("Last-Modified", self.date_time_string(os.fstat(fonte.fileno()).st_mtime))
            self.end_headers()
            return fonte

        def copyfile(self, source, outputfile):
            restante = self._intervalo_restante
            if restante is None:
                return super().copyfile(source, outputfile)
            while restante:
                bloco = source.read(min(restante, 64 * 1024))
                if not bloco:
                    break
                outputfile.write(bloco)
                restante -= len(bloco)

        def responder(self, status, dados):
            conteudo = json.dumps(dados, ensure_ascii=False, default=serializar_json).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(conteudo)

        def origem_valida(self, escrita=False):
            host = self.headers.get("Host", "")
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origem = self.headers.get("Origin")
            valido = host in hosts and (origem is None or origem == f"http://{host}")
            valido = valido and self.headers.get("Sec-Fetch-Site", "") != "cross-site"
            if escrita:
                valido = valido and origem == f"http://{host}" and secrets.compare_digest(
                    self.headers.get("X-Financas-Token", ""), servico.token)
            if not valido:
                self.responder(403, {"erro": "Esta operação só é aceita pela aplicação local."})
            return valido

        def tratar(self, operacao):
            try:
                return operacao()
            except Conflito as erro:
                self.responder(409, {"erro": str(erro), "revisao": servico.revisao})
            except (ValueError, TypeError, KeyError) as erro:
                self.responder(400, {"erro": str(erro)})
            except Exception:
                registrador.exception("Falha na operação local")
                self.responder(500, {"erro": "Não foi possível concluir a operação. Consulte o terminal do servidor."})

        def do_GET(self):
            if not self.origem_valida():
                return
            caminho = urlsplit(self.path).path
            if caminho == "/api/estado":
                self.tratar(lambda: self.responder(200, servico.atualizar_estado()))
            elif caminho == "/api/catalogo":
                self.tratar(lambda: self.responder(200, servico.catalogo()))
            elif caminho.startswith("/api/"):
                self.responder(404, {"erro": "Operação desconhecida."})
            elif self.arquivo_permitido(caminho):
                super().do_GET()

        def arquivo_permitido(self, caminho):
            arquivo, raiz = self.arquivo(caminho)
            relativo = arquivo.relative_to(raiz) if arquivo.is_relative_to(raiz) else None
            extensoes = {".html", ".css", ".js", ".mjs", ".svg", ".json", ".parquet", ".ico", ".woff2"}
            permitido = relativo is not None and not any(p.startswith(".") for p in relativo.parts)
            permitido = permitido and (caminho == "/" or arquivo.suffix.lower() in extensoes)
            if not permitido:
                self.responder(403, {"erro": "Arquivo fora da aplicação."})
            return permitido

        def arquivo(self, caminho):
            caminho = unquote(urlsplit(caminho).path)
            if caminho.startswith("/dados/"):
                return (servico.destino / caminho[len("/dados/"):]).resolve(), servico.destino
            return (servico.frontend / caminho.lstrip("/")).resolve(), servico.frontend

        def translate_path(self, path):
            return str(self.arquivo(path)[0])

        def do_HEAD(self):
            if self.origem_valida() and self.arquivo_permitido(urlsplit(self.path).path):
                super().do_HEAD()

        def list_directory(self, path):
            self.responder(403, {"erro": "Listagem de diretórios indisponível."})
            return None

        def do_PUT(self):
            self.escrever()

        def do_POST(self):
            self.escrever()

        def escrever(self):
            if not self.origem_valida(escrita=True):
                return
            def executar():
                tamanho = int(self.headers.get("Content-Length", "0"))
                if not 0 < tamanho <= 1_048_576 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Envie um objeto JSON de até 1 MB.")
                dados = json.loads(self.rfile.read(tamanho))
                if not isinstance(dados, dict):
                    raise ValueError("O corpo deve ser um objeto JSON.")
                caminho = urlsplit(self.path).path
                if caminho == "/api/regras/previa" and self.command == "POST":
                    return self.responder(200, servico.previa(dados))
                if caminho == "/api/faturas/sincronizar" and self.command == "POST":
                    status, resultado = servico.sincronizar_faturas(self.headers.get("If-Match"))
                    return self.responder(status, resultado)
                tipos = {"/api/categorias": "categoria", "/api/regras": "regra"}
                if caminho in tipos and self.command == "PUT":
                    dados["tipo"] = tipos[caminho]
                elif not (caminho == "/api/ajustes" and self.command == "PUT" or caminho == "/api/publicar" and self.command == "POST"):
                    return self.responder(404, {"erro": "Operação desconhecida."})
                status, resultado = servico.gravar(dados, self.headers.get("If-Match"), republicar=caminho == "/api/publicar")
                self.responder(status, resultado)
            self.tratar(executar)

    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)
    servidor.daemon_threads = True
    return servidor


def servir_local(config: Configuracao, frontend: Path, porta: int = 8000, destino: Path | None = None) -> None:
    servico = ServicoLocal(config, frontend, destino)
    servico.preparar()
    with criar_servidor(servico, porta) as servidor:
        print(f"Where Is the Money: http://127.0.0.1:{servidor.server_port}")
        print("Edição local habilitada. Ctrl+C para parar.")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nparado.")
