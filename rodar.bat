@echo off
rem ===========================================================================
rem  where_is_the_money — sobe o pipeline inteiro e o dashboard.
rem
rem  Uso:
rem      rodar.bat                  ingere da API real e abre o dashboard
rem      rodar.bat offline          usa as fixtures sinteticas, sem tocar a rede
rem      rodar.bat --so-servir      nao ingere; so abre o que ja foi publicado
rem      rodar.bat --porta 8080     troca a porta (padrao 8000)
rem
rem  Os argumentos podem ser combinados: rodar.bat offline --porta 8080
rem
rem  Sobre os codigos de saida: este script NAO os engole. Os codigos 2, 3 e 6
rem  sao avisos — o dado foi gravado, mas alguma coisa precisa da sua atencao —
rem  entao o pipeline continua e o aviso aparece no fim. Os codigos 1 e 5
rem  significam que nao ha o que publicar, e aí ele para.
rem ===========================================================================

setlocal EnableDelayedExpansion

rem A saida do projeto e UTF-8. Sem isto o console do Windows mostra os acentos
rem trocados, e um alerta ilegivel e um alerta perdido.
chcp 65001 >nul 2>&1

set "MODO=online"
set "INGERIR=sim"
set "PORTA=8000"

rem Avisos acumulados durante o pipeline, mostrados juntos no fim. Sao
rem flags separadas em vez de uma string concatenada porque o `echo` do batch
rem engasga com parenteses e acentos no meio de um bloco `if`.
set "AVISO_PARCIAL="
set "AVISO_DEGRADADO="
set "AVISO_FRESCOR="

rem --- argumentos ------------------------------------------------------------
:ler_argumentos
if "%~1"=="" goto fim_argumentos
if /i "%~1"=="offline"     ( set "MODO=offline"    & shift & goto ler_argumentos )
if /i "%~1"=="online"      ( set "MODO=online"     & shift & goto ler_argumentos )
if /i "%~1"=="--so-servir" ( set "INGERIR=nao"     & shift & goto ler_argumentos )
if /i "%~1"=="--porta"     ( set "PORTA=%~2"       & shift & shift & goto ler_argumentos )
echo [ERRO] argumento desconhecido: %~1
echo.
echo Uso: rodar.bat [offline^|online] [--so-servir] [--porta N]
exit /b 1
:fim_argumentos

cd /d "%~dp0backend" || (
    echo [ERRO] nao encontrei a pasta backend ao lado deste .bat.
    exit /b 1
)

rem O modo offline usa um banco SEPARADO, e isto nao e detalhe: as fixtures sao
rem sinteticas, e ingeri-las no mesmo arquivo do seu extrato real misturaria
rem dado inventado com dado de verdade na mesma tabela. Depois de misturado,
rem nao da para separar — a camada raw nao guarda de onde veio cada linha.
set "BANCO="
if /i "%MODO%"=="offline" set "BANCO=--banco dados\offline.duckdb"

echo ===========================================================================
echo  where_is_the_money  ^|  modo: %MODO%  ^|  porta: %PORTA%
if /i "%MODO%"=="offline" echo  banco: dados\offline.duckdb  ^(separado do real, por seguranca^)
echo ===========================================================================
echo.

if /i "%MODO%"=="offline" (
    echo [AVISO] Modo offline: os dados sao SINTETICOS.
    echo         O dashboard vai mostrar as fixtures, nao o seu extrato.
    echo         Para voltar ao real: rodar.bat
    echo.
)

rem --- checagens de ambiente -------------------------------------------------
rem Falhar aqui, com a instrucao do que fazer, e muito melhor que falhar no
rem meio da ingestao com um traceback.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    echo        Instale o Python 3.11+ e marque "Add python.exe to PATH".
    exit /b 1
)

python -c "import financas" >nul 2>&1
if errorlevel 1 (
    echo [ERRO] o pacote 'financas' nao esta instalado.
    echo.
    echo        Isto nao e opcional: o pythonpath do pyproject.toml vale so
    echo        para o pytest, nao para o 'python -m'. Rode, de dentro de
    echo        backend\:
    echo.
    echo            pip install -e ".[dev]"
    echo.
    exit /b 1
)

if not exist ".env" (
    echo [ERRO] falta o arquivo backend\.env
    echo        Crie a partir do exemplo:  copy env.example .env
    echo        e preencha PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET.
    exit /b 1
)

if not exist "config\regras.toml" (
    echo [ERRO] falta o arquivo backend\config\regras.toml
    echo        Crie a partir do exemplo:
    echo            copy config\regras.example.toml config\regras.toml
    exit /b 1
)

rem --- 1. ingestao -----------------------------------------------------------
if /i "%INGERIR%"=="nao" (
    echo [1/4] ingestao pulada ^(--so-servir^)
    echo.
    goto views
)

echo [1/4] ingerindo ^(modo %MODO%^)...
python -m financas ingerir --modo %MODO% %BANCO%
set "CODIGO=!ERRORLEVEL!"
echo.

if "!CODIGO!"=="0" goto views
if "!CODIGO!"=="3" ( set "AVISO_PARCIAL=1"   & goto views )
if "!CODIGO!"=="6" ( set "AVISO_DEGRADADO=1" & goto views )
if "!CODIGO!"=="5" (
    echo [PARANDO] A API respondeu, mas nao havia nada para ingerir ^(codigo 5^).
    echo           A explicacao completa saiu acima. Sem dado nao ha o que publicar.
    exit /b 5
)
echo [PARANDO] a ingestao falhou com codigo !CODIGO!. Leia a mensagem acima.
exit /b !CODIGO!

rem --- 2. views --------------------------------------------------------------
:views
echo [2/4] aplicando as views SQL...
python -m financas views --modo %MODO% %BANCO%
set "CODIGO=!ERRORLEVEL!"
if not "!CODIGO!"=="0" (
    echo.
    echo [PARANDO] as views falharam ^(codigo !CODIGO!^). Sem elas nao ha o que publicar.
    exit /b !CODIGO!
)
echo.

rem --- 3. frescor ------------------------------------------------------------
rem Roda depois das views e antes de publicar, de proposito: se alguma
rem instituicao parou de trazer dado, o aviso aparece ANTES de voce olhar um
rem dashboard que parece completo.
echo [3/4] verificando frescor...
python -m financas frescor --modo %MODO% %BANCO%
set "CODIGO=!ERRORLEVEL!"
if "!CODIGO!"=="2" set "AVISO_FRESCOR=1"
echo.

rem --- 4. publicar -----------------------------------------------------------
echo [4/4] publicando os Parquet para o frontend...
python -m financas publicar --modo %MODO% %BANCO%
set "CODIGO=!ERRORLEVEL!"
if not "!CODIGO!"=="0" (
    echo.
    echo [PARANDO] a publicacao falhou ^(codigo !CODIGO!^).
    exit /b !CODIGO!
)
echo.

rem --- avisos acumulados -----------------------------------------------------
rem Repetidos aqui, no fim, porque o dashboard vai abrir parecendo completo e
rem o aviso ja teria rolado para fora da tela.
if defined AVISO_PARCIAL   goto mostrar_avisos
if defined AVISO_DEGRADADO goto mostrar_avisos
if defined AVISO_FRESCOR   goto mostrar_avisos
goto servir

:mostrar_avisos
echo ===========================================================================
echo  ATENCAO - o dashboard vai abrir, mas o dado pode estar incompleto:
if defined AVISO_PARCIAL   echo   - alguma instituicao FALHOU na ingestao (codigo 3)
if defined AVISO_DEGRADADO echo   - alguma conexao pede acao sua: MFA, senha ou reautorizar (codigo 6)
if defined AVISO_FRESCOR   echo   - alguma instituicao PAROU de atualizar (codigo 2)
echo.
echo  Os detalhes sairam acima. Reautorizar se faz em meu.pluggy.ai.
echo ===========================================================================
echo.

:servir

rem --- servidor --------------------------------------------------------------
rem O navegador abre antes do servidor porque o servidor bloqueia este console
rem ate o Ctrl+C. O DuckDB-WASM exige origem HTTP: abrir o index.html por
rem file:// mostra tela vazia e um erro de console que nao explica nada.
echo Abrindo http://127.0.0.1:%PORTA% ...
start "" "http://127.0.0.1:%PORTA%"

echo.
echo ===========================================================================
echo  Servidor no ar. Ctrl+C para parar.
echo.
echo  O bloco de publicacao aparece uma segunda vez abaixo: `publicar --servir`
echo  republica antes de subir o servidor. E idempotente e custa milissegundos,
echo  entao nao ha o que corrigir — e so a mesma saida repetida.
echo ===========================================================================
python -m financas publicar --modo %MODO% %BANCO% --servir --porta %PORTA%

endlocal
