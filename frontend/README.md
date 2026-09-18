# Frontend de investigação

Interface local em português, sem build e sem instalação de pacotes JavaScript.

```powershell
# Na pasta backend, com o pacote instalado:
python -m financas servir
```

Abra o endereço local informado pelo comando. Não abra por `file://`: DuckDB-WASM
usa Worker e requisições HTTP. O módulo DuckDB-WASM 1.29.0 é carregado do jsDelivr.
O manifesto v2 aponta para uma publicação imutável de Parquet; arquivos reais em
`dados/` continuam fora do Git.

## Telas

- **Resumo:** total, comparação temporal, categorias, meses e instituições.
- **Explorar gastos:** categorias, matriz mensal, estabelecimentos, transações,
  busca, ordenação, paginação e detalhes de origem.
- **Bancos e cartões:** despesas, contas e posições, matriz por categoria e
  cobertura. Sincronização e última transação são informações diferentes.
- **Recorrências e parcelas:** sugestões, confirmações, ignoradas e encerradas;
  calendário limitado aos futuros informados pela fonte.
- **Patrimônio:** posições por conta/investimento e moeda. Série apenas quando
  existem ao menos dois retratos completos com composição comparável.
- **Revisão:** pendências, classificações e atributos em lote com desfazer,
  catálogo, associações Pluggy, aliases, regras com prévia, compras e auditoria.
- **Ferramentas SQL:** consultas locais de leitura com até 500 linhas exibidas.
  O filtro global não altera a consulta SQL escrita pelo usuário.

Os filtros globais persistem entre telas. Gráficos abrem seus lançamentos e o
botão de voltar restaura a análise anterior. O modo por compra usa a view
`compras`: não agrupa parcelas por semelhança. A revisão de compras inclui futuros
e todo o histórico, explicitamente identificados na tela.

## Organização

- `js/core.mjs`: períodos, filtros comuns, formatação, grupos, posições e guarda SQL.
- `js/dados.mjs`: DuckDB-WASM, manifesto e troca de conexão; API de personalizações.
- `js/ui.mjs`: componentes acessíveis, escape HTML e delegação de ações.
- `js/app.mjs`: estado compartilhado, navegação, análises e detalhes.
- `js/revisao.mjs`: classificações, regras, catálogo, compras e auditoria.
- `styles.css`: layout responsivo e estados de foco.

Views publicadas definem gasto, categoria e compra. Os relatórios carregam a
publicação completa na memória e aplicam o mesmo filtro comum às linhas e seus
detalhamentos. Não há consultas à Pluggy durante edições. Valores DECIMAL são
convertidos explicitamente a DOUBLE na view do navegador; ausências ficam nulas.

A API local usa token, revisão e origem. Uma resposta 202 indica que a correção
já foi salva: a interface oferece **Publicar novamente**, sem repetir a mutação.
Um conflito 409 exige recarga explícita. Sem API, relatórios permanecem acessíveis
e as edições mostram sua indisponibilidade.

## Verificação

```powershell
node --test frontend/tests/*.test.mjs
node --check frontend/js/app.mjs
node --check frontend/js/revisao.mjs
```

Os testes são sintéticos e verificam períodos parciais/fechados, filtros e aspas,
valores ausentes, compras, snapshots comparáveis, SQL de leitura e revisão da API.
Verificação visual e interações de edição devem usar uma publicação sintética.
