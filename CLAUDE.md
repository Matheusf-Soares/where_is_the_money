# WHERE_IS_THE_MONEY

Pipeline pessoal de ingestão e análise de gastos, alimentado pela API da Pluggy
via Open Finance.

> Este arquivo é o contexto de trabalho: escopo, restrições e as decisões já
> tomadas que o código novo precisa respeitar. A explicação longa de *por que*
> cada peça é assim está em [`backend/README.md`](backend/README.md).

---

## 1. Objetivo

Consolidar transações de múltiplas instituições financeiras em um único
repositório analítico, para responder perguntas como:

- Quanto eu gastei por mês, por categoria e por estabelecimento?
- Quais assinaturas recorrentes estão ativas e quanto custam por ano?
- Quais categorias fugiram da média dos meses anteriores?
- Qual a evolução do meu patrimônio (contas + investimentos) ao longo do tempo?

O projeto substitui apps de controle financeiro prontos, que engessam a
categorização e não permitem séries históricas customizadas.

---

## 2. Estado atual e escopo

| Fase | O quê | Situação |
|---|---|---|
| **1** | Ingestão, persistência, views SQL, testes, CLI | ✅ completa — 224 testes passando |
| **2** | Categorização própria sobre a categoria da Pluggy | em andamento — resolução em 3 camadas pronta |
| **3** | Frontend consumindo as views | ✅ estático + DuckDB-WASM, 6 abas |
| **4** | *(talvez)* migração para GCP com execução agendada | — |

A fase 1 nunca foi validada contra a API real. Isso é feito por mim, fora deste
ambiente. Enquanto não acontecer, todo comportamento contra a Pluggy de verdade
é hipótese — ver "Lacunas conhecidas" no README.

**Fora de escopo enquanto a fase 2 não começar** (não implementar, não sugerir,
não criar arquivos): dashboards, gráficos, frontend, Streamlit, Metabase,
Looker, Docker, CI/CD, deploy em nuvem, autenticação. É um projeto local,
single-user.

O frontend virá depois, consumindo as views SQL definidas no backend. Por isso
vale a regra: **as views são o contrato público do backend.** Mudança em
`gastos`, `recorrencias` ou `patrimonio` é mudança de contrato, não detalhe
interno.

---

## 3. Layout do repositório

```
where_is_the_money/
├─ CLAUDE.md          # este arquivo — vale para o repositório inteiro
├─ backend/           # fase 1, completa
│  ├─ README.md       # a documentação de verdade do backend
│  ├─ pyproject.toml
│  ├─ src/financas/   # o pacote
│  ├─ sql/            # staging/ e marts/
│  ├─ tests/
│  └─ config/
└─ frontend/          # fase 3, ainda vazia
```

**Todo comando de backend roda de dentro de `backend/`.** O `pyproject.toml`
declara `pythonpath = ["src"]` e `testpaths = ["tests"]`, ambos relativos; e
`raiz_do_projeto()` resolve para `backend/`, que é onde ficam `.env`,
`config/` e `sql/`.

### O pacote se chama `financas`

Não `backend.financas`, não `src.financas`. **`financas`.** Importe sempre
assim, inclusive entre módulos do próprio pacote:

```python
from financas.config import Configuracao      # ✅
from backend.src.financas.config import ...   # ❌ ModuleNotFoundError
```

Nos testes, `conftest` é importado direto (`from conftest import RAIZ`), porque
o pytest põe `tests/` no path.

Isso já quebrou uma vez: um find/replace ao mover o projeto para `backend/`
reescreveu 13 arquivos para o prefixo errado e derrubou a suíte inteira. Se for
mover diretório de novo, confira os imports antes de commitar.

---

## 4. Contexto da fonte de dados

### Pluggy e o conector MeuPluggy

A Pluggy é uma plataforma de Open Finance. Para uso pessoal, o fluxo tem dois
lados que são frequentemente confundidos:

| Portal | URL | Papel |
|---|---|---|
| Meu Pluggy | `meu.pluggy.ai` | Onde o titular autoriza os bancos e vê os dados |
| Dashboard | `dashboard.pluggy.ai` | Onde o desenvolvedor cria aplicações e obtém credenciais |

São contas de login separadas. A ponte entre os dois é o conector **MeuPluggy
(id 200)**: dentro da aplicação criada no Dashboard, cria-se um item com esse
conector, autenticando com a conta do Meu Pluggy. É isso que expõe os dados
reais já autorizados para consumo via API.

O ambiente usado é o de **Desenvolvimento**. Produção é uma trilha comercial
com análise de vendas, desnecessária para uso pessoal.

### Instituições conectadas

PicPay, Santander, Nubank, Inter e Rico Investimentos (contexto *Investments*),
mais 3 cartões de crédito, um deles vinculado à Rico.

### Endpoints relevantes

```
POST /auth                                  -> apiKey (validade ~2h)
GET  /items                                 -> conexões autorizadas
GET  /accounts?itemId=                      -> contas de um item
GET  /transactions?accountId=&from=&page=   -> extrato, paginado
GET  /investments?itemId=                   -> posição de investimentos
```

Host: `https://api.pluggy.ai`

O vocabulário `item → account → transaction` se repete no código inteiro, e a
ingestão percorre exatamente essa hierarquia.

---

## 5. Arquitetura e fluxo de dados

```
API Pluggy
    |
    v
[ingestão]  autentica, itera items -> accounts -> transactions
    |       normaliza JSON aninhado em colunas planas
    v
[raw]       raw_transacoes, raw_contas, raw_investimentos, cfg_*
    |       append-only lógico, upsert por chave natural, idempotente
    v
[staging]   stg_transacoes, stg_contas, stg_investimentos
    |       limpeza, tipagem, deduplicação, marcação de ruído
    v
[marts]     gastos, recorrencias, patrimonio   <- contrato do frontend
```

### Os três princípios

Quando houver dúvida de projeto, decida por eles.

1. **Idempotência acima de tudo.** Rodar a ingestão duas vezes seguidas não
   pode duplicar nem alterar nada. A garantia vem do upsert por chave natural,
   nunca de um `INSERT` puro.
2. **Raw é sagrado.** A camada raw guarda o que a API devolveu, sem regra de
   negócio aplicada, incluindo o JSON original em `payload_json`. Toda decisão
   discutível vive em staging ou marts, onde pode ser revista sem reingestão.
3. **Regras de negócio em SQL, não em Python.** Python busca e grava. A lógica
   analítica fica em `.sql` versionados, legíveis e testáveis isoladamente. Se a
   regra estivesse em Python, o frontend teria que reimplementá-la.

### Stack

Python 3.11+ (`tomllib` na stdlib) · `httpx` (o SDK oficial da Pluggy é Node) ·
DuckDB · `pytest` · **sem ORM**.

Migração futura para BigQuery está no radar, então evite construções exclusivas
do DuckDB nas views de marts quando houver equivalente padrão — na prática,
`lower(x) LIKE lower(y)` em vez de `ILIKE`, e `EXTRACT` em vez de `date_trunc`.

---

## 6. Decisões já tomadas

Estas não são preferências: são invariantes que a suíte de testes protege.
Mudá-las é decisão de projeto, não refactor.

### Chave natural depende da natureza do dado

| Dado | Natureza | Chave |
|---|---|---|
| Transação | **evento** | `id` |
| Conta | **estado** | `(id, data_posicao)` |
| Investimento | **estado** | `(id, data_posicao)` |

Saldo e posição são fotografados uma vez por dia. Se a chave de estado fosse só
o `id`, cada ingestão sobrescreveria o retrato anterior e o banco guardaria
apenas hoje — tornando impossível a pergunta sobre evolução do patrimônio. E
não se reconstrói um dado que nunca foi gravado.

`ingerido_em` é gravado uma vez e nunca mais tocado. `atualizado_em` só se mexe
quando o `payload_json` realmente muda — se fosse carimbado a cada execução, o
teste de idempotência passaria sem verificar nada.

### O staging marca, o mart decide

Uma transação excluída não desaparece: continua em `stg_transacoes` com a
bandeira que a tirou (`e_pagamento_de_fatura`, `e_transferencia_propria`,
`e_aplicacao`). "Por que esse gasto sumiu do total?" se responde com um
`SELECT`, não caçando um `WHERE`.

### Filtro não pode ser hardcoded

Os padrões vivem em `config/regras.toml`, são carregados em tabelas `cfg_*` no
DuckDB, e as views fazem `JOIN` contra elas. Mudar um filtro é editar o TOML e
rodar `python -m financas views`, sem reingerir nada.

**Há uma guarda estrutural sobre isso:** um teste falha se qualquer `.sql`
versionado contiver `LIKE '...'` com literal, ou citar nome de instituição fora
de comentário. Um `LIKE '%fatura%'` escrito direto na view passaria em todos os
testes de comportamento e ainda assim quebraria a promessa do projeto.

O campo `instituicao` das regras também é padrão LIKE, não igualdade: o
`connector.name` da API nem sempre é o nome curto, e a Rico vem como
`"Rico Investimentos"`. Escreva `"rico%"`.

### `valor` em `gastos` é positivo

Na raw um gasto é `-100`, porque é assim que a API manda. A inversão acontece
uma vez só, na view. Somar despesa negativa é fonte constante de erro de sinal.

### O grão de `gastos` é a transação

Nunca um agregado mensal. Agregar depois é trivial; o caminho inverso é
impossível.

### `criar_cliente()` é o único lugar que escolhe entre online e offline

`ClienteHttp` e `ClienteFixtures` cumprem o mesmo `Protocol`. O resto do
pipeline recebe um `Cliente` pronto e não pergunta de onde vieram os dados. É
isso que permite testar ingestão, upsert e views inteiras sem rede. Não
introduza um `if modo ==` em nenhum outro módulo.

---

## 7. As nove armadilhas do domínio

Já custaram tempo. São requisitos, não sugestões.

| # | Armadilha | Onde é tratada |
|---|---|---|
| 1 | **Dupla contagem de cartão** — a compra aparece na conta `CREDIT` e o pagamento da fatura de novo na `BANK` | `cfg_padroes_fatura` → `e_pagamento_de_fatura` |
| 2 | **Transferência entre contas próprias** não é gasto | `cfg_contrapartes_proprias` → `e_transferencia_propria` |
| 3 | **Aporte não é despesa** | `raw_investimentos` separada + `cfg_padroes_aplicacao` → `e_aplicacao` |
| 4 | **Consentimento expira** — o pipeline não quebra, silenciosamente para de trazer dado novo | `frescor.py` + código de saída ≠ 0 |
| 5 | **Latência de até 24h** — "hoje" nunca está completo | `frescor_dias_padrao` |
| 6 | **`apiKey` vive ~2h** | autentica a cada execução, nunca persiste o token |
| 7 | **Paginação obrigatória** | o cliente itera até acabar; há teste |
| 8 | **`itemId` muda** a cada reautorização | é atributo, nunca identidade |
| 9 | **Histórico começa ~2025-08** | `data_inicial` no `regras.toml` |

**A Pluggy classifica nativamente as armadilhas 1, 2 e 3** — as categorias
`Credit card payment`, `Same person transfer` e `Investments`. `cfg_categorias_ruido`
soma esse sinal ao filtro de texto por **OR**, nunca no lugar dele: categorização
por ML erra, o texto pega o que ela errar, e se a feature estiver desligada na
conta a categoria vem nula e só o texto atua. Duas redes, buracos diferentes.

⚠️ **Categorização é feature premium na Pluggy**, opt-in depois do trial. Se
estiver desligada, `category` vem nulo em todas as transações e tanto o de-para
quanto o reforço ficam inertes. Conferir na primeira ingestão real.

A armadilha 4 é a que define o desenho: **o modo de falha que este projeto
combate é o silencioso.** Filtro que nunca casa, instituição que parou de
atualizar, página 2 que ninguém buscou — tudo isso "funciona" e devolve número
errado. Prefira sempre falhar alto a passar batido.

---

## 8. Como rodar

Tudo a partir de `backend/`.

```bash
cd backend
pip install -e ".[dev]"                             # OBRIGATÓRIO, veja abaixo

cp env.example .env                                 # preencha as credenciais
cp config/regras.example.toml config/regras.toml    # preencha suas chaves Pix

python -m pytest                                    # 276 testes, sem rede
```

⚠️ **O `pip install -e .` não é opcional.** Sem ele, `python -m financas`
falha com `No module named financas`. O `pythonpath = ["src"]` do
`pyproject.toml` é configuração **do pytest** — ele faz a suíte passar e não
põe nada no path do `python -m`. Se o comando falhar, é quase sempre isto:
o install não foi feito, ou foi feito de fora de `backend/`.

Depois do install, os comandos rodam **de qualquer diretório**
(`raiz_do_projeto()` se resolve pelo `__file__`), e existe também o atalho
`financas ingerir` sem o `python -m`.

### Comandos

```bash
python -m financas ingerir     # baixa e grava na camada raw
python -m financas views       # recarrega cfg_* e aplica os .sql
python -m financas frescor     # alguém parou de trazer dado novo?
python -m financas categorias  # regra morta e cobertura da categorização
python -m financas publicar    # exporta as views em Parquet para o frontend
python -m financas status      # o que existe no banco
```

Para ver o dashboard: `python -m financas publicar --servir` e abrir
`http://127.0.0.1:8000`. **Não abra o `index.html` por `file://`** — o
DuckDB-WASM usa Web Workers e range requests, e os dois exigem origem HTTP.

Flags globais: `--modo online|offline`, `--banco CAMINHO`, `-v` (ou `-vv`).
`ingerir` aceita `--desde` e `--hoje`; `frescor`, `--hoje`; `categorias`,
`--sincronizar` e `--saida`.

`categorias --sincronizar` é o único comando que faz sentido rodar online sem
ingerir nada: busca `GET /categories`, que é lista de referência igual para
todos os clientes, e gera o bloco `[[mapa_categoria]]` com os ids reais. Os ids
da Pluggy não estão publicados em lugar nenhum — adivinhá-los produz um de-para
que não casa nada e falha calado.

### Códigos de saída

Pensados para `cron` e script, onde ninguém lê a saída na hora:

| Código | Significado |
|---|---|
| `0` | tudo certo |
| `1` | configuração inválida, uso errado, falha inesperada |
| `2` | **alguma instituição parou de atualizar** (armadilha 4) |
| `3` | ingestão parcial: pelo menos uma instituição falhou |
| `4` | regra de categoria que nunca casou: filtro que não filtra |

### Configuração: duas fontes

| | `.env` | `config/regras.toml` |
|---|---|---|
| Guarda | segredos e caminhos | filtros de negócio |
| Muda quando | você troca de máquina | você descobre um padrão novo no extrato |
| Versionado? | não (só `env.example`) | não (só `regras.example.toml`) |

Os dois ficam fora do git por motivos diferentes: o `.env` tem segredo, e o
`regras.toml` identifica contas próprias por nome do titular e chave Pix.

`config.py` falha **cedo** (antes da primeira requisição), **por inteiro**
(acumula todos os problemas) e **dizendo o que fazer** (aponta onde conseguir o
valor). Mantenha as três ao adicionar configuração nova.

---

## 9. Convenções

- Nomes de tabelas, colunas, views, funções e variáveis **em português**.
  Docstrings e comentários também.
- Nada de credenciais no código. Tudo por variável de ambiente, conforme
  `env.example`.
- `.env`, `*.duckdb` e qualquer arquivo com dado financeiro real ficam no
  `.gitignore`. **Este repositório não pode conter dado pessoal.**
- Testes usam exclusivamente dados sintéticos — titular "Fulano de Tal", CPF
  `12345678909`, telefone `31900001111`. Nenhum teste depende de rede ou
  credencial. Há um teste que falha se um valor real vazar para
  `tests/fixtures/`.
- `ClienteHttp` é testado com `httpx.MockTransport`: as requisições são
  construídas e roteadas de verdade, mas nenhum socket é aberto.

---

## 10. AMBIENTE DE EXECUÇÃO: LEIA ANTES DE RODAR QUALQUER COISA

O ambiente onde você está executando é **restrito e sandboxed**. Assuma que
permissões são limitadas por padrão.

- **Muitos comandos vão falhar por permissão, não por erro seu.** Acesso à
  rede, escrita fora do diretório do projeto, instalação de pacotes do sistema,
  serviços em background, portas de escuta: qualquer um pode ser bloqueado.
- **Chamadas à API Pluggy provavelmente não vão funcionar daqui.** Não trate
  isso como bug a ser contornado. O código de ingestão é escrito e testado
  contra fixtures e mocks; a validação contra a API real é feita por mim, fora
  deste ambiente.
- **Se um comando for bloqueado, pare e me avise.** Não tente rotas
  alternativas para burlar a restrição, não troque de gerenciador de pacotes,
  não escreva fora do projeto. Descreva o que foi bloqueado e siga com o que
  der para fazer.
- **Antes de instalar qualquer dependência, pergunte.** Prefira biblioteca
  padrão sempre que a diferença for pequena.
- **Nada destrutivo.** Sem `rm -rf`, sem reescrever histórico do git, sem
  alterar arquivos fora do repositório.
- **Não crie credenciais nem `.env` preenchidos.** Apenas `env.example` com
  placeholders.

---

## 11. Como trabalhar aqui

- **Incrementos pequenos e revisáveis.** A cada etapa concluída, pare e mostre
  o que fez antes de seguir.
- **Se uma decisão de modelagem tiver mais de um caminho razoável**, apresente
  as opções com o trade-off em vez de escolher sozinho.
- **Rode `python -m pytest` antes de dizer que terminou.** 224 testes, ~15s,
  sem rede.
- Antes de escrever código, leia [`backend/README.md`](backend/README.md): ele
  explica o *porquê* de cada decisão listada na seção 6.
