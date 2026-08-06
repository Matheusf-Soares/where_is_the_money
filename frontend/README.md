# frontend

Dashboard e ferramenta de auditoria. Um arquivo, sem build, sem `npm install`.

```bash
cd ../backend
python -m financas publicar --servir
# abre em http://127.0.0.1:8000
```

## Por que estático + DuckDB-WASM

O DuckDB roda **dentro do navegador** e consulta os Parquet que
`financas publicar` exporta. Não existe API entre o backend e a tela.

A razão não é economia de infraestrutura — é o princípio 3 do projeto, *regra de
negócio em SQL, não em Python*. Uma API REST tem gravidade própria: no dia em
que a tela precisar de "gasto por categoria com média móvel", o caminho de menor
resistência é escrever isso em Python dentro do endpoint. Aí a regra passa a
existir em dois lugares, e as views deixam de ser o contrato.

Aqui o frontend fala SQL contra as **mesmas views versionadas** do backend. Uma
consulta que você testa no DuckDB local funciona colada na aba SQL sem mudar
nada. Não há onde esconder lógica.

Dois custos, ambos honestos:

- **É um retrato, não tempo real.** Os dados são do último `publicar`. Para um
  pipeline diário contra uma fonte com 24h de latência, isso não custa nada — e
  o cabeçalho carimba a data para a tela nunca fingir que está ao vivo.
- **Precisa de `http://`.** Web Workers e range requests não funcionam por
  `file://`. Daí o `--servir`, que sobe um `http.server` da biblioteca padrão
  ligado só em `127.0.0.1`.

O volume torna isso viável: ~3.000 transações por ano dão uns 100 KB em Parquet.
O dataset inteiro cabe na memória do navegador sem esforço, e paginação
server-side seria engenharia para um problema que não existe.

## As abas

| Aba | Para quê |
|---|---|
| **Visão geral** | Último mês, média mensal, patrimônio líquido, custo anual de assinaturas. Gasto por mês, por grupo e por categoria. |
| **Gastos** | `gastos` inteira, com busca e filtros por mês, instituição, grupo e categoria. |
| **Auditoria** | A mais importante. Ver abaixo. |
| **Recorrências** | Assinaturas detectadas, com a coluna `ativa` separando o que ainda cobra do que parou. |
| **Patrimônio** | Série temporal do líquido e composição por instituição no retrato mais recente. |
| **SQL** | Consulta livre sobre as seis tabelas. |

## A aba Auditoria

É a que responde *"cadê aquele lançamento?"* — a pergunta que um dashboard
comum não responde.

**Conciliação.** No topo, a prova de que nada some:

```
débito bruto na camada raw     R$ 8.735,05
− pagamento de fatura          R$ 2.500,30
− transferência própria        R$ 2.800,00
− aplicação e resgate          R$ 2.000,00
= gasto de verdade             R$ 1.434,75
diferença                      R$ 0,00  ✓ fecha
```

É o mesmo invariante de conservação que a suíte de testes verifica, só que
auditável a olho nu. Se a diferença não for zero, tem dado sumindo ou sendo
contado duas vezes.

**Tabela completa.** Toda transação de `stg_transacoes`, incluindo as excluídas
— cada uma com a etiqueta da bandeira que a tirou, a categoria resolvida, a
camada que decidiu (`regra`, `mapa` ou `padrao`) e a categoria crua da Pluggy ao
lado. A busca cobre descrição, estabelecimento, categoria e id.

É a materialização do princípio "o staging marca, o mart decide": nada
desaparece, tudo tem motivo declarado.

## Se a tela vier vazia

1. Rodou `python -m financas publicar`?
2. Está em `http://` e não `file://`?
3. `dados/` existe ao lado do `index.html`?

A tela mostra o erro real e esse checklist em vez de ficar em branco.

## Nota sobre conta gratuita da Pluggy

Categorização de transação é feature premium, opt-in depois do trial. Em conta
gratuita `category` vem nulo em todas as transações — o de-para não resolve
nada e só as regras por texto do `regras.toml` atuam. O `publicar` detecta isso
e põe uma tarja no topo da tela, porque um gráfico "por categoria" quase todo em
*Sem categoria* precisa dizer por quê.

## Onde ficam os dados

`frontend/dados/` — Parquet + `manifesto.json`. **Está no `.gitignore`**: é o
seu extrato inteiro, em arquivo.
