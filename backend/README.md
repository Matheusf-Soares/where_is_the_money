# where_is_the_money

Pipeline pessoal de ingestão e análise de gastos, alimentado pela API da Pluggy
via Open Finance.

A ideia é simples: puxar o extrato de todas as instituições financeiras para um
banco local e responder, com SQL, perguntas que os apps de controle financeiro
prontos não deixam responder — quanto gastei por categoria, quais assinaturas
estão ativas, qual categoria fugiu da média, como o patrimônio evoluiu.

> A aplicação inclui relatórios locais e classificação persistente pela interface.
> Para abrir, execute `python -m financas servir`. O [guia da aplicação](../README.md)
> descreve os filtros, as duas leituras das compras e a publicação versionada.

---

## Índice

1. [O problema que o projeto resolve](#1-o-problema-que-o-projeto-resolve)
2. [De onde vêm os dados](#2-de-onde-vêm-os-dados)
3. [A arquitetura em três camadas](#3-a-arquitetura-em-três-camadas)
4. [Os três princípios](#4-os-três-princípios)
5. [As armadilhas do domínio](#5-as-armadilhas-do-domínio)
6. [Configuração: duas fontes, dois propósitos](#6-configuração-duas-fontes-dois-propósitos)
7. [Modo offline: desenvolver sem rede](#7-modo-offline-desenvolver-sem-rede)
8. [Estrutura de diretórios](#8-estrutura-de-diretórios)
9. [Como rodar](#9-como-rodar)
10. [Estado atual](#estado-atual)

---

## 1. O problema que o projeto resolve

Quem tem conta em quatro instituições diferentes não tem um extrato — tem
quatro. Os apps de controle financeiro prontos até agregam isso, mas engessam a
categorização e não deixam construir série histórica customizada.

O objetivo aqui é ter **os dados brutos em casa**, num banco analítico local, e
tratar a análise como um problema de SQL. O frontend consulta as views publicadas
em Parquet através do DuckDB-WASM. Por isso vale a regra: **as views são
o contrato público do projeto**.

**Fora de escopo:** nuvem, orçamentos, metas e classificação por IA.
É um projeto local, single-user; a API local grava personalizações e permite
atualizar as faturas dos cartões já conhecidos.

---

## 2. De onde vêm os dados

### Os dois portais da Pluggy

Esse é o ponto que mais confunde quem começa. A Pluggy tem dois portais, com
contas de login **separadas**:

| Portal | URL | Para quê |
|---|---|---|
| **Meu Pluggy** | `meu.pluggy.ai` | Onde você, como titular, autoriza os bancos |
| **Dashboard** | `dashboard.pluggy.ai` | Onde você, como desenvolvedor, cria a aplicação e pega as credenciais |

A ponte entre os dois é o conector **MeuPluggy (id 200)**: dentro da aplicação
criada no Dashboard, cria-se um *item* com esse conector, autenticando com a
conta do Meu Pluggy. É isso que expõe, para a API, os dados que você já
autorizou do outro lado.

O ambiente usado é o de **Desenvolvimento**. Produção é trilha comercial, com
análise de vendas — desnecessária para uso pessoal.

### O vocabulário da API

Três conceitos encaixados, que se repetem no código inteiro:

```
item          uma conexão autorizada com uma instituição  (ex.: "meu Nubank")
 └─ account   uma conta dentro dessa instituição          (BANK ou CREDIT)
     └─ transaction   uma linha do extrato
```

A ingestão percorre exatamente essa hierarquia: para cada item, busca as contas;
para cada conta, pagina as transações.

### Instituições conectadas

PicPay, Santander, Nubank, Inter e Rico Investimentos — mais 3 cartões de
crédito, um deles vinculado à Rico. Os dados de investimento da Rico vêm num
contexto separado (*Investments*) e são tratados como tal.

### Endpoints usados

```
POST /auth                                     -> apiKey (validade ~2h)
GET  /items                                    -> conexões autorizadas
GET  /accounts?itemId=                         -> contas de um item
GET  /v2/transactions?accountId=&dateFrom=&after=  -> extrato, por cursor
GET  /investments?itemId=                      -> posição de investimentos
GET  /categories                               -> taxonomia (referência)
GET  /bills?accountId=                          -> faturas oficiais do cartão
```

Host: `https://api.pluggy.ai`.


**O extrato mudou de endereço.** `GET /transactions` responde **HTTP 410
ENDPOINT_DEPRECATED** e manda usar `GET /v2/transactions`. As duas diferenças
que importam:

- **Pagina por cursor, não por página.** O corpo é
  `{"results": [...], "next": <cursor|null>}`, e o cursor volta como `after`.
  `page` e `pageSize` são recusados.
- **O recorte de data mudou de nome:** `from` virou `dateFrom`. A v2 valida por
  whitelist e responde 400 `property from should not exist`.

Os demais endpoints continuam na v1, paginando por `page`/`totalPages` — por
isso o cliente tem as duas formas de paginar.

---

## 3. A arquitetura em três camadas

O fluxo é o de um pipeline ELT clássico, adaptado para rodar na sua máquina:

```
                    API Pluggy
                        │
                        │  httpx, autenticação a cada execução, paginação
                        ▼
              ┌───────────────────┐
              │     INGESTÃO      │   Python: busca e grava. Só isso.
              │  (financas/*.py)  │   Achata o JSON aninhado em colunas planas
              └─────────┬─────────┘
                        │
                        ▼
     ┌──────────────────────────────────────┐
     │  RAW      raw_transacoes  (evento)   │  Fiel à API. Nenhuma regra
     │           raw_contas      (estado)   │  aplicada. Upsert idempotente
     │           raw_investimentos (estado) │  por chave natural.
     │           cfg_*  ◄───────────────────┼── espelho do regras.toml
     └──────────────────┬───────────────────┘
                        │
                        │  SQL versionado
                        ▼
     ┌──────────────────────────────────────┐
     │  STAGING  stg_transacoes             │  Limpeza, tipagem, dedup,
     │           stg_contas                 │  marcação de ruído.
     │           stg_investimentos          │
     └──────────────────┬───────────────────┘
                        │
                        │  SQL versionado + tabelas cfg_*
                        ▼
     ┌──────────────────────────────────────┐
     │  MARTS    gastos       ◄─────────────┼── contrato do futuro frontend
     │           recorrencias               │
     │           patrimonio                 │
     └──────────────────────────────────────┘
```

### As views

| View | Grão | Responde |
|---|---|---|
| `stg_transacoes` | transação | *por que* essa transação foi excluída — uma bandeira por armadilha |
| `stg_contas` | conta × dia | retratos, com o mais recente sinalizado |
| `stg_investimentos` | posição × dia | idem, para investimentos |
| **`gastos`** | transação | quanto gastei, por mês, categoria, estabelecimento |
| **`recorrencias`** | assinatura | o que é assinatura ativa e quanto custa por ano |
| **`patrimonio`** | instituição × dia | como o patrimônio evoluiu |
| **`faturas`** | fatura × cartão | total oficial e mês de vencimento |
| **`cobertura_faturas`** | cartão | última coleta de faturas e limitações do detalhe |
| **`lancamentos_fatura_aberta`** | transação pendente sem fatura | prévia e lançamentos excluídos/ambíguos, com motivo |
| **`faturas_abertas`** | cartão | subtotal conhecido da prévia, créditos e pagamentos separados |

O staging **marca**, o mart **decide**. Uma transação excluída não desaparece:
ela continua em `stg_transacoes` com a bandeira que a tirou, então "por que esse
gasto sumiu do meu total?" se responde com um `SELECT`, não caçando um `WHERE`.

Duas escolhas em `gastos` que evitam erro recorrente:

- **`valor` é positivo.** Na raw um gasto é `-100`, porque é assim que a API
  manda. Somar despesa negativa é fonte constante de erro de sinal; a inversão
  acontece uma vez só, na view.
- **`ano` e `mes` separados, via `EXTRACT`.** `date_trunc` tem assinatura
  diferente no BigQuery, e a migração está no radar.

O grão é a transação, e não um agregado mensal: agregar depois é trivial, o
caminho inverso é impossível.

### Datas derivadas antes da publicação

`transacoes_analiticas` mantém `data` como data do lançamento, usada pelos filtros
existentes. Os campos aditivos `dia_semana` (português) e `dia_semana_iso`
(1 segunda-feira a 7 domingo) correspondem a essa data. `data_gasto` prefere
`creditCardMetadata.purchaseDate` válida, senão usa `data`; `origem_data_gasto`
informa `purchaseDate` ou `data`. `dia_semana_gasto` e `dia_semana_gasto_iso`
correspondem a `data_gasto`. Datas ausentes continuam nulas.

Em `compras`, todos esses dias correspondem à data final da compra. Compras
parceladas confirmadas usam a data informada na confirmação e origem
`compra_confirmada`; compras avulsas preservam a origem da transação.
Essas transformações acontecem nas views SQL e já seguem prontas nos Parquet,
sem modificar o JSON bruto nem exigir nova ingestão.

### Fatura em andamento: contrato da prévia parcial

A [referência de transações da Pluggy](https://docs.pluggy.ai/en/reference/transaction/transactions-retrieve)
define `billForecastDate` como período previsto `YYYY-MM`; ele não é vínculo
oficial como `billId`. `PENDING` também pode conter parcelas futuras. Por isso
as duas views novas não usam saldo, limite ou total de compras para inventar
uma fatura oficial e nunca vinculam uma previsão a uma fatura fechada.

`lancamentos_fatura_aberta` contém somente contas `CREDIT`, transações `PENDING`
e `billId` ausente/vazio. Expõe todos os campos de `transacoes_analiticas` mais:

| Campo | Significado |
|---|---|
| `mes_previsao_fonte` | previsão válida `YYYY-MM`, preservada como informação da fonte, sem assumir vencimento |
| `ultimo_fechamento`, `ultimo_mes_fechado` | limites observados nas faturas já fechadas |
| `tipo_operacao_fonte` | `operationType` original |
| `tipo_lancamento` | `despesa`, `credito`, `pagamento` ou `sem_valor` |
| `classificacao_periodo` | `andamento`, `futura`, `anterior` ou `sem_associacao` |
| `incluida_previa` | verdadeiro somente para `andamento` |
| `previsao_inconsistente` | previsão igual/anterior ao último mês fechado |

A seleção usa a data de lançamento, preservando a separação entre a compra e
cada parcela: datas futuras ficam fora; datas anteriores ao último fechamento
ficam em `anterior`. Entre lançamentos recentes, a menor previsão posterior ao
último mês fechado determina a primeira coorte; previsões posteriores a ela
ficam em `futura`. Quando falta fechamento, uma previsão válida pode delimitar
a primeira coorte, mas não cria uma data de fechamento/vencimento.

Lançamentos estritamente posteriores ao fechamento podem entrar como valores
recentes conhecidos mesmo sem previsão ou com previsão inconsistente. A
inconsistência permanece explícita: isso não confirma o mês da próxima fatura.
No próprio dia do fechamento, só uma previsão posterior ao último mês fechado
resolve o limite; os demais ficam em `sem_associacao`. Sem previsão e sem
fechamento, ou sem data, não se presume associação.

`faturas_abertas` contém uma linha por cartão, inclusive cartões sem pendências.
Identificadores: `id_conta`, `instituicao`, `conta`, `numero_cartao`. O campo
`mes_previsao_fonte` resume a primeira coorte válida incluída; se houver apenas
previsões inconsistentes, mostra a previsão observada com a respectiva contagem
de inconsistências. Nenhum desses campos é um mês de vencimento confirmado.

Os valores são `subtotal_despesas_brl`, `subtotal_creditos_brl`, `pagamentos_brl`
e `liquido_conhecido_brl` (despesas menos créditos). Pagamentos identificados
pelas regras existentes, por `operationType=PAGAMENTO_FATURA`, ou por
`operationType=PAGAMENTO` com valor assinado positivo no cartão ficam separados
e **não reduzem** o líquido do ciclo. `PAGAMENTO` em um débito continua sendo
despesa; `ESTORNO` em um crédito continua sendo crédito. A classificação usa
tipo/sinal normalizados, sem depender da descrição ou categoria da fonte.
Moedas estrangeiras só entram em BRL quando existe
`amountInAccountCurrency` comprovado numa conta BRL. Sem qualquer valor BRL
conhecido incluído, os quatro totais são nulos, não uma fatura de zero reais.
Se apenas pagamentos têm valor BRL conhecido, `pagamentos_brl` conserva esse
valor, mas despesas, créditos e líquido continuam nulos: um pagamento não
comprova o valor dos gastos do ciclo.

Contagens: `qtd_lancamentos`, `qtd_despesas`, `qtd_creditos`, `qtd_pagamentos`
e `qtd_sem_conversao` consideram apenas a prévia incluída. `qtd_futuras`,
`qtd_anteriores`, `qtd_sem_associacao` e `qtd_previsao_inconsistente` tornam as
limitações auditáveis. `primeira_data`/`ultima_data` delimitam os lançamentos
incluídos; `coletado_em` é a última coleta bem-sucedida de transações registrada
em `log_faturas`, podendo ser nula. `previa_parcial` é sempre verdadeiro.
Uma atualização de `PENDING` para `POSTED` com `billId` remove o lançamento
da prévia e o disponibiliza no detalhamento da fatura oficial.

As duas views são publicadas na mesma geração atômica das demais tabelas.
Sua existência não implica que a origem exponha todos os gastos da fatura
aberta; a validação contra o aplicativo bancário continua necessária.

### Por que três camadas e não uma

A tentação é fazer o Python já gravar tudo limpo, numa tabela só. O problema é
que **toda limpeza é uma decisão discutível**, e decisões mudam.

Exemplo concreto: você decide que "pagamento de fatura" não é gasto e filtra
isso na ingestão. Três meses depois descobre que o Santander escreve
`PAGTO CARTAO` e não `PAGAMENTO DE FATURA` — seu filtro nunca pegou nada. Se o
filtro estava na ingestão, o dado se perdeu e é preciso reingerir tudo. Se
estava numa view, você corrige o SQL e roda de novo: **os dados brutos nunca
saíram do lugar**.

É por isso que:

- **raw** guarda o que a API devolveu, incluindo o JSON original completo numa
  coluna `payload_json`. Se a Pluggy adicionar um campo que a normalização não
  previu, ele continua recuperável sem reingestão.
- **staging** faz o que é objetivamente certo: tipagem, deduplicação, datas.
- **marts** é onde mora a opinião: o que conta como gasto, o que é assinatura.

A ingestão é cara (rede, latência, consentimento que expira). A transformação é
barata (SQL local, roda em segundos). Separar as duas significa que errar na
parte barata custa barato.


**A API não devolve chave Pix.** `paymentData` identifica a contraparte por
`name` e por `documentNumber.value`, e é só isso. Um `pixKey` chegou a existir
no código, lido de `paymentData.receiver.pixKey` — campo que só as fixtures
tinham. Contra a API real a coluna vinha sempre nula, e os testes de
transferência própria passavam sem exercitar nada. Por isso `contraparte` (que
casa no documento estruturado) é preferível a `chave_pix` (que só olha texto)
sempre que o identificador for um CPF.

### Stack

| Peça | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.11+ | `tomllib` na biblioteca padrão |
| HTTP | `httpx` | o SDK oficial da Pluggy é Node |
| Banco | DuckDB | analítico, local, arquivo único, SQL próximo do padrão |
| Testes | `pytest` | — |
| ORM | nenhum | SQL direto; aqui o SQL *é* a regra de negócio |

Migração futura para BigQuery está no radar, então as views de marts evitam
construções exclusivas do DuckDB quando existe equivalente padrão. Na prática:
`lower(x) LIKE lower(y)` em vez de `ILIKE`.

---

## 4. Os três princípios

Tudo no projeto sai destes três. Quando houver dúvida de projeto, decida por eles.

### 1. Idempotência acima de tudo

Rodar a ingestão duas vezes seguidas não pode duplicar nem alterar nada. Isso
não é preciosismo: consentimento de Open Finance expira, rede cai, e a chance de
você rodar o mesmo comando duas vezes por insegurança é alta.

A garantia vem do **upsert por chave natural**, nunca de um `INSERT` puro. O
`itemId` não serve como chave de nada persistente, porque **uma reautorização
gera um `itemId` novo** para a mesma instituição — ele é gravado como atributo,
não como identidade.

Qual é a chave natural depende da natureza do dado, e essa distinção é a decisão
de modelagem mais importante do projeto:

| Dado | Natureza | Chave | Por quê |
|---|---|---|---|
| Transação | **evento** | `id` | Aconteceu uma vez, tem id próprio e estável |
| Conta | **estado** | `(id, data_posicao)` | O saldo de hoje não é o de ontem |
| Investimento | **estado** | `(id, data_posicao)` | O CDB rende todo dia |

Saldo e posição são fotografados uma vez por dia. Se a chave fosse só o `id`,
cada ingestão sobrescreveria o retrato anterior e o banco guardaria **apenas
hoje** — tornando impossível responder "qual a evolução do meu patrimônio ao
longo do tempo?", que é um dos objetivos do projeto. E não dá para consertar
depois: não se reconstrói um dado que nunca foi gravado.

Duas colunas de controle completam o desenho:

- **`ingerido_em`** é gravado uma vez e nunca mais tocado.
- **`atualizado_em`** só se mexe quando o `payload_json` realmente muda.

O segundo detalhe é o que dá sentido ao teste de idempotência. Se `atualizado_em`
fosse carimbado a cada execução, a segunda rodada alteraria o banco e o teste
passaria sem verificar nada de real.

### 2. Raw é sagrado

A camada raw é append-only lógico. Nada de negócio acontece ali. Se uma
transação chegou torta da API, ela fica torta em raw e é consertada em staging.

### 3. Regras de negócio em SQL, não em Python

Python busca e grava. A lógica analítica vive em arquivos `.sql` versionados,
que dá para abrir, ler e rodar isoladamente. Duas consequências práticas:

- Revisar uma regra é ler um `SELECT`, não caçar um `if` no meio de um loop.
- O futuro frontend consome as views. Se a regra estivesse em Python, o frontend
  teria que reimplementá-la.

---

## 5. As armadilhas do domínio

Nove delas já custaram tempo e são tratadas como requisito, não sugestão. Esta
tabela é o mapa de onde cada uma é resolvida:

| # | Armadilha | Por que morde | Onde é tratada |
|---|---|---|---|
| 1 | **Dupla contagem de cartão** | A compra aparece na conta `CREDIT`; o pagamento da fatura aparece **de novo** na conta `BANK`. Somar tudo dobra o gasto | `cfg_padroes_fatura` → `e_pagamento_de_fatura` |
| 2 | **Transferência entre contas próprias** | Mover R$ 500 do Nubank para o Santander não é gasto, mas polui o total | `cfg_contrapartes_proprias` → `e_transferencia_propria` |
| 3 | **Aporte não é despesa** | Investir não é gastar | `raw_investimentos` separada, **e** `cfg_padroes_aplicacao` → `e_aplicacao` |
| 4 | **Consentimento expira** | O pipeline **não quebra**: ele silenciosamente para de trazer dados novos. Esse é o pior tipo de falha | [`frescor.py`](src/financas/frescor.py) + saída ≠ 0 |
| 5 | **Latência de até 24h** | "Hoje" nunca está completo em conector regulado | tolerância configurável (`frescor_dias_padrao`) |
| 6 | **`apiKey` vive ~2h** | Token velho falha no meio da execução | autentica a cada execução, nunca persiste o token |
| 7 | **Paginação obrigatória** | Assumir que a página 1 é tudo perde histórico em silêncio | o cliente itera até acabar; há teste para isso |
| 8 | **`itemId` muda** | Reautorizar gera um item novo para o mesmo banco | chave natural é o `id` da transação |
| 9 | **Histórico começa ~2025-08** | Antes disso não há o que buscar | `data_inicial` no `regras.toml` |
| 14 | **Saldo de fatura anterior relançado** | "Saldo em atraso" na fatura seguinte repete compras já contadas | `cfg_padroes_saldo_anterior` → `e_saldo_anterior` |
| 15 | **Pendente reemitida com id novo** | A pendente antiga continua no raw e conta junto com a lançada | `e_pendente_substituida` em `stg_transacoes` |
| 16 | **Rendimento não informado** | Ações e FIIs vêm sem valor aplicado; inventar zero afirma algo falso | `rendimento` NULL em `stg_investimentos` |

**Nenhum desses filtros é hardcoded.** As armadilhas 1 e 2 dependem do texto da
descrição, que varia por instituição — e texto que varia por instituição é
configuração, não código. Os padrões vivem no `regras.toml`, são carregados em
tabelas `cfg_*` no DuckDB, e as views fazem `JOIN` contra elas. Mudar um filtro é
editar o TOML e rodar `python -m financas views`, sem reingerir nada.

Uma sutileza que já custou um bug: o campo `instituicao` das regras também é
padrão LIKE, não igualdade. O `connector.name` da API nem sempre é o nome curto
— a Rico vem como `"Rico Investimentos"`, então `instituicao = "rico"` não
casaria com nada. Escreva `"rico%"`. Um filtro que nunca casa falha em silêncio,
que é justamente o modo de falha que este projeto combate, então a configuração
recusa padrão com maiúscula em vez de deixar passar.

---

## 6. Configuração: duas fontes, dois propósitos

A separação é intencional e vale entender:

| | `.env` | `config/regras.toml` |
|---|---|---|
| **Guarda** | segredos e caminhos | filtros de negócio |
| **Exemplo** | `PLUGGY_CLIENT_SECRET`, caminho do banco | o que conta como pagamento de fatura |
| **Depende de** | a máquina onde roda | como suas contas se comportam |
| **Muda quando** | você troca de máquina | você descobre um padrão novo no extrato |
| **Versionado?** | não (só `env.example`) | não (só `regras.example.toml`) |

Ambos ficam fora do git, por motivos diferentes: o `.env` tem segredo, e o
`regras.toml` identifica contas próprias por nome do titular e chave Pix — dado
pessoal, que não pode entrar no repositório.

Para começar:

```bash
cp env.example .env                                 # e preencha as credenciais
cp config/regras.example.toml config/regras.toml    # e preencha suas chaves Pix
```

### Como a configuração é validada

[`src/financas/config.py`](src/financas/config.py) segue três regras:

**Falha cedo.** Um erro de configuração aparece antes de a primeira requisição
sair, não no meio da ingestão.

**Falha por inteiro.** Os problemas são acumulados e reportados de uma vez.
Corrigir um `.env` uma variável por execução é irritante:

```
Configuração inválida:
  - PLUGGY_CLIENT_ID é obrigatória com FINANCAS_MODO=online. Pegue em
    dashboard.pluggy.ai > sua aplicação > credenciais e coloque no .env
  - PLUGGY_CLIENT_SECRET é obrigatória com FINANCAS_MODO=online. (...)
  - PLUGGY_API_URL deve começar com http:// ou https://, recebi 'api.pluggy.ai'
  - FINANCAS_TIMEOUT deve ser maior que zero, recebi '-5'
```

**Falha dizendo o que fazer.** A mensagem aponta onde conseguir o valor, não só
que ele falta.

Detalhes menores, mas deliberados: credencial só é obrigatória no modo `online`
(cobrar isso em `offline` atrapalha o desenvolvimento); `Configuracao.__repr__`
esconde o secret, porque esse objeto acaba em log e em traceback; e o `.env` é
lido por um parser de ~25 linhas em biblioteca padrão, em vez de uma dependência
a mais.

---

## 7. Modo offline: desenvolver sem rede

O projeto é desenvolvido num ambiente sandboxed, onde chamadas à API da Pluggy
provavelmente são bloqueadas. Mas a restrição virou uma boa decisão de projeto.

`FINANCAS_MODO` alterna entre duas implementações do **mesmo cliente**:

| Modo | Implementação | Origem dos dados | Uso |
|---|---|---|---|
| `offline` (padrão) | `ClienteFixtures` | JSON em `tests/fixtures/pluggy/` | desenvolvimento e testes |
| `online` | `ClienteHttp` | API real | ingestão de verdade, fora do sandbox |

As duas cumprem o mesmo `Protocol`, e `criar_cliente()` é o único lugar do
projeto que escolhe entre elas. O resto do pipeline recebe um `Cliente` pronto e
não pergunta de onde vieram os dados — é isso que permite testar ingestão,
upsert e views inteiras sem rede.

As fixtures reproduzem o cenário real: 5 instituições, 8 contas (3 delas
cartão), 27 transações e 2 investimentos. Cada armadilha tem um caso plantado
ali — pagamento de fatura nos dois lados, Pix entre contas próprias, TED para a
corretora, aporte em CDB, e o PicPay parado desde agosto para exercitar o
detector de frescor.

Os testes usam **exclusivamente** dados sintéticos: titular "Fulano de Tal", CPF
`12345678909`, telefone `31900001111` — todos inventados. Nenhum teste depende
de rede, credencial ou do seu extrato. Um teste verifica isso explicitamente,
falhando se um valor real vazar para dentro de `tests/fixtures/`.

O `ClienteHttp` é testado com `httpx.MockTransport`: as requisições são
construídas e roteadas de verdade, mas nenhum socket é aberto. É assim que
paginação, retry, reautenticação e tradução de erro têm cobertura sem rede.

### O que garante que os dois modos não divergem

Se o cliente offline se comportasse diferente do real, o modo offline estaria
testando outro programa — e a confiança no desenvolvimento sem rede seria
falsa. Três testes fecham essa porta:

- **Uma API falsa serve as fixtures por HTTP**, com páginas de 2 registros, e o
  pipeline inteiro roda por ela. São mais de 20 requisições reais atravessando
  `/auth`, paginação, normalização, upsert e views.
- **Um teste de contrato** roda o pipeline duas vezes, uma por cada cliente, e
  compara `SELECT *` das duas camadas raw. Qualquer divergência falha.
- **Um invariante de conservação** verifica que a soma dos débitos fecha:
  `gastos + excluídos == total`. Sobrar significa dado perdido; faltar,
  dado contado duas vezes.

Há ainda uma **guarda estrutural** contra o filtro hardcoded: nenhum `.sql`
versionado pode conter `LIKE '...'` com literal, nem citar nome de instituição
fora de comentário. Um `LIKE '%fatura%'` escrito direto na view passaria em todos
os testes de comportamento e ainda assim quebraria a promessa do projeto — só
apareceria no dia em que o Santander mudasse a redação.

---

## 8. Estrutura de diretórios

O repositório está dividido em duas fases: `backend/` (fase 1, completa) e
`frontend/` (fase 3, concluída). **Todo comando abaixo roda de dentro de
`backend/`** — `pythonpath`, `testpaths` e `raiz_do_projeto()` são relativos a
ele. O pacote se chama `financas`, e é assim que se importa, sempre:
`from financas.config import ...`.

```
where_is_the_money/
├─ CLAUDE.md                     # escopo, restrições e decisões (raiz do repo)
├─ frontend/                     # fase 3: dashboard estático + DuckDB-WASM
└─ backend/
   ├─ README.md                  # este arquivo
   ├─ pyproject.toml             # deps e configuração do pytest
   ├─ env.example                # variáveis de ambiente (só placeholders)
   │
   ├─ config/
   │  └─ regras.example.toml     # filtros das armadilhas 1, 2, 3 e 4
   │
   ├─ src/financas/
   │  ├─ config.py               # lê .env + regras.toml, valida, falha cedo
   │  ├─ pluggy/
   │  │  ├─ cliente.py           # auth, erros HTTP, retry, paginação
   │  │  └─ fixtures.py          # cliente offline: mesma interface, lê do disco
   │  ├─ persistencia/
   │  │  ├─ banco.py             # conexão DuckDB, DDL, upsert idempotente
   │  │  └─ schema.sql           # DDL de raw_* e cfg_*
   │  ├─ normalizacao.py         # achata o JSON aninhado em colunas planas
   │  ├─ ingestao.py             # orquestra items → accounts → transactions
   │  ├─ frescor.py              # detecta instituição que parou de atualizar
   │  ├─ views.py                # aplica os .sql na ordem certa
   │  └─ cli.py                  # argparse: ingerir | frescor | views | status
   │
   ├─ sql/
   │  ├─ staging/                # 01_stg_transacoes, 02_stg_contas, 03_stg_investimentos
   │  └─ marts/                  # 01_gastos, 02_recorrencias, 03_patrimonio
   │
   └─ tests/
      ├─ conftest.py             # banco em memória, relógio falso, cliente offline
      ├─ fixtures/pluggy/        # JSONs sintéticos
      ├─ test_config.py          # validação e mensagens de erro
      ├─ test_cliente.py         # auth, paginação, retry, erros HTTP
      ├─ test_normalizacao.py    # achatamento e conversões
      ├─ test_persistencia.py    # idempotência do upsert
      ├─ test_ingestao.py        # travessia e isolamento de falha
      ├─ test_frescor.py         # armadilha 4
      ├─ test_views.py           # as armadilhas 1, 2 e 3 nas views
      ├─ test_cli.py             # subcomandos e códigos de saída
      └─ test_ponta_a_ponta.py   # o pipeline inteiro, pela API HTTP
```

---

## 9. Como rodar

Tudo a partir de `backend/`.

```bash
# 1. Dependências — o -e não é opcional: é ele que põe `financas` no path.
#    Sem isso, `python -m financas` falha com "No module named financas",
#    porque o pythonpath do pyproject.toml vale só para o pytest.
pip install -e ".[dev]"

# 2. Configuração local (nenhum dos dois vai para o git)
cp env.example .env
cp config/regras.example.toml config/regras.toml

# 3. Testes — não precisam de rede nem de credencial
python -m pytest
```

### Comandos

```bash
python -m financas ingerir     # baixa e grava na camada raw
python -m financas views       # recarrega cfg_* e aplica os .sql
python -m financas frescor     # alguém parou de trazer dado novo?
python -m financas categorias  # regra morta e cobertura da categorização
python -m financas diagnostico # testa a conexão com a Pluggy passo a passo
python -m financas publicar    # exporta as views em Parquet para o frontend
python -m financas faturas     # atualiza faturas e transações dos cartões e publica
python -m financas status      # o que existe no banco
```

Para consultar e editar: `python -m financas servir` e abrir
`http://127.0.0.1:8000`. **Não abra o `index.html` por `file://`** — o
DuckDB-WASM usa Web Workers e range requests, e os dois exigem origem HTTP.

Flags globais: `--modo online|offline`, `--banco CAMINHO`, `-v` (ou `-vv`).
`ingerir` aceita `--desde` e `--hoje`; `frescor`, `--hoje`.

### Faturas por mês de vencimento

`ingerir` coleta também as faturas dos cartões. Para atualizar somente esse
produto e os vínculos dos lançamentos, use `python -m financas faturas`; o
comando aceita `--hoje` e `--destino`. Abrir `servir` não chama a Pluggy.

O total vem de `totalAmount` da entidade oficial, nunca do saldo do cartão nem
da soma das compras. A referência mensal é `dueDate`. O total permanece na
moeda original; somente faturas BRL entram no consolidado em reais. Um total
oficial não é uma afirmação de saldo restante: os pagamentos documentados pela
Pluggy correspondem a eventos de ciclos de faturamento e não são subtraídos
automaticamente.

`raw_faturas` preserva o JSON e usa chave `(id, id_conta)`, com o mesmo upsert
idempotente das demais tabelas raw. `log_faturas` mantém, por cartão, a última
tentativa, a última coleta válida e o estado `nao_coletado`, `sucesso`,
`sem_faturas` ou `falha`. Ausência não representa zero; uma falha preserva a
coleta anterior e não impede os demais cartões.

O detalhe usa apenas `creditCardMetadata.billId` junto ao ID da conta. A API
v2 de transações não documenta filtro `billId`, então a coleta específica relê
o histórico desde a data inicial configurada ou a primeira transação local,
o que vier antes. A ingestão geral reaproveita os extratos já consultados na
mesma execução, respeitando `--desde`. A cobertura informa a janela consultada
e falhas no extrato, pois faturas abertas e alguns conectores podem não trazer
todos os vínculos. Nenhuma associação é inferida por descrição, valor ou data.

Referências oficiais: [faturas](https://docs.pluggy.ai/en/docs/products/credit-card-bills),
[listagem](https://docs.pluggy.ai/en/reference/bill/bills-list) e
[transações v2](https://docs.pluggy.ai/en/reference/transaction/transactions-list-by-cursor).

### Códigos de saída

Pensados para `cron` e script, onde ninguém lê a saída na hora:

| Código | Significado |
|---|---|
| `0` | tudo certo |
| `1` | configuração inválida, uso errado, falha inesperada |
| `2` | **alguma instituição parou de atualizar** (armadilha 4) |
| `3` | ingestão parcial: pelo menos uma instituição falhou |
| `6` | uma conexão pediu ação sua (MFA, senha, reautorizar) |
| `4` | regra de categoria que nunca casou: filtro que não filtra |
| `5` | **a API respondeu mas não havia nada para ingerir** |

Os códigos 2 e 3 são o ponto da armadilha 4: o pipeline que "funciona" mas
parou de trazer dado precisa gritar, não passar batido.

Erro de uso — comando inexistente, data malformada — sai com `1`, e **não** com
o `2` que o argparse usa por convenção. O `2` aqui significa "alguma
instituição parou de atualizar", e um `cron` que ramifica por código de saída
leria um `--desde` digitado errado como consentimento vencido, indo reautorizar
um banco que não tem problema nenhum.

---

## Estado atual

O backend está sendo construído em incrementos revisáveis, nesta ordem:

| # | Etapa | Situação |
|---|---|---|
| a | **Configuração** — env + regras, validação, `env.example` | ✅ concluída |
| b | **Cliente Pluggy** — auth, erro HTTP, paginação, modo offline | ✅ concluída |
| c | **Persistência** — schema DuckDB e upsert idempotente | ✅ concluída |
| d | **CLI** — `ingerir`, `views`, `frescor`, `status` | ✅ concluída |
| e | **Views SQL** — `gastos`, `recorrencias`, `patrimonio` | ✅ concluída |
| f | **Testes de ponta a ponta** — armadilhas 1, 2, 3 e 7 | ✅ concluída |

A suíte inclui contratos financeiros, personalizações, publicação atômica e API
local com dados sintéticos. Execute `python -m pytest -q` para verificar a versão
do checkout. Nenhum teste usa credenciais reais; testes HTTP locais verificam a API.

- [`config.py`](src/financas/config.py) — configuração e regras
- [`pluggy/cliente.py`](src/financas/pluggy/cliente.py) · [`pluggy/fixtures.py`](src/financas/pluggy/fixtures.py) — API real e offline
- [`normalizacao.py`](src/financas/normalizacao.py) — achatamento do JSON
- [`persistencia/schema.sql`](src/financas/persistencia/schema.sql) · [`persistencia/banco.py`](src/financas/persistencia/banco.py) — DDL e upsert
- [`ingestao.py`](src/financas/ingestao.py) — travessia e isolamento de falha
- [`frescor.py`](src/financas/frescor.py) — detector da armadilha 4
- [`views.py`](src/financas/views.py) · [`cli.py`](src/financas/cli.py) — orquestração
- [`sql/staging/`](sql/staging/) · [`sql/marts/`](sql/marts/) — contratos legados e analíticos
- [`personalizacoes.py`](src/financas/personalizacoes.py) — validação, histórico e desfazer
- [`servidor.py`](src/financas/servidor.py) — API em loopback e conflitos explícitos
- [`publicacao.py`](src/financas/publicacao.py) — gerações imutáveis e manifesto atômico

Tudo que a seção 8 descreve existe no disco. A `frontend/` na raiz guarda o
aplicação modular sem build, alimentada por `python -m financas publicar`.
`python -m financas servir` reaplica as views, publica e habilita a edição local.

### O tamanho do problema, em números

Rodando as views contra as fixtures sintéticas:

```
débito bruto na camada raw : R$ 8.735,05
gasto real (view gastos)   : R$ 1.434,75
ruído removido             : R$ 7.300,30   — 84% do total
```

Sem os filtros das armadilhas 1, 2 e 3, o relatório mostraria **seis vezes** o
gasto real. Não é margem de erro: é a diferença entre um número útil e um número
inventado.

### Lacunas conhecidas

- ~~**Um item por instituição é uma suposição.**~~
  **CONFERIDO em 17/09/2026:** são quatro items, um por instituição — mas
  todos com `connector.name = "MeuPluggy"`, porque o conector 200 é agregador.
  A suposição sobre a QUANTIDADE estava certa; a sobre o NOME, não. Por isso
  `instituicao` virou campo obrigatório em `[[item]]`.

  O texto original segue abaixo, para registro:

- **Um item por instituição é uma suposição.** O conector MeuPluggy pode
  devolver um único item agregando tudo. As fixtures assumem cinco itens; se a
  API real fizer diferente, mudam as fixtures, não o código — a ingestão percorre
  `items → accounts` de qualquer jeito.
- **Transferência via TED entre contas próprias** só é pega pelo nome do
  titular. Se o extrato de alguma instituição não trouxer o nome, escapa.
- ~~**`patrimonio` assume que `balance` de conta `CREDIT` é positivo**~~
  **RESOLVIDO em 17/09/2026:** conferido contra a API real — o `balance` do
  cartão vem `+854,87`, positivo, como a view assume. A suposição estava certa.

  O texto original segue abaixo, para registro:

- **`patrimonio` assume que `balance` de conta `CREDIT` é positivo** e representa
  o valor devido. Se alguma instituição devolver negativo, o sinal inverte e o
  patrimônio fica inflado. Conferir na primeira ingestão real.
- **Os padrões de `regras.toml` são um chute informado.** Só o extrato real dirá
  se o Santander escreve `PAGTO CARTAO` ou outra coisa. `stg_transacoes` existe
  justamente para auditar isso: as bandeiras mostram o que cada filtro pegou.

### Antes da primeira ingestão real

Três coisas dependem de você, não de código:

1. **Rotacionar o `PLUGGY_CLIENT_SECRET`** no dashboard.pluggy.ai. Ele esteve
   num `env.example`, arquivo destinado a versionamento.
2. **Preencher `config/regras.toml`** com as demais chaves Pix e conferir como o
   seu nome sai no extrato. Sem isso a armadilha 2 fica meio tratada.
3. **Conferir os padrões de fatura** contra as descrições reais. `stg_transacoes`
   foi feita para isso:

```sql
-- o que cada filtro pegou
SELECT instituicao, descricao, valor, e_pagamento_de_fatura,
       e_transferencia_propria, e_aplicacao
FROM stg_transacoes
WHERE e_pagamento_de_fatura OR e_transferencia_propria OR e_aplicacao;

-- e, mais importante, o que escapou
SELECT instituicao, descricao, valor FROM gastos
WHERE lower(descricao) LIKE '%pix%' OR lower(descricao) LIKE '%ted%'
   OR lower(descricao) LIKE '%fatura%'
ORDER BY valor DESC;
```

A segunda consulta é a que revela filtro faltando: transferência ou fatura que
sobrou em `gastos` é padrão que ninguém escreveu ainda.

### Evoluções futuras

Orçamentos, metas, sincronização em nuvem e classificação por IA não fazem parte
da etapa atual. A prioridade é investigar gastos com números verificáveis.
