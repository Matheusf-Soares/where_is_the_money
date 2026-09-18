# Investigação de gastos — plano aprovado

Implementar a revisão aprovada pelo usuário em 17/09/2026. Produto pessoal,
local, em português, voltado a investigar gastos. Preservar Python, DuckDB,
SQL como regra de negócio e DuckDB-WASM sem build no navegador.

## Entregas

1. Base analítica: moedas sem soma indevida, cobertura por instituição,
   classificações persistentes, compras confirmadas e recorrências revisáveis.
2. Publicação atômica e servidor local de edição, com validação de origem e
   conflitos de atualização explícitos.
3. Seis telas: Resumo, Explorar gastos, Bancos e cartões, Recorrências e
   parcelas, Patrimônio, Revisão. SQL permanece em Ferramentas.
4. Filtros compartilhados, comparação entre períodos, gráficos interativos,
   matriz mensal e por banco, detalhamento reversível e classificação em lote.
5. Testes sintéticos de invariantes financeiros, persistência/API/publicação,
   filtros e verificações visuais e funcionais no navegador.

## Regras

- Categorias próprias em duas camadas (macro/categoria); essencialidade e
  comportamento separados e editáveis. Não inferir essencialidade.
- Precedência: manual > regra da interface > regra TOML > mapa da interface >
  mapa TOML > padrão. Preservar descrição e classificação originais.
- API local de personalizações; nunca alterar payload raw nem chamar Pluggy
  durante uma correção. Corrigir, simular regra e desfazer são fluxos distintos.
- Por parcela é o padrão. Por compra contabiliza o total uma vez na data
  confirmada, com cobertura explícita; nenhuma associação por palpite.
- BRL somente com valor BRL original, conversão fornecida pela conta ou valor
  explicitamente confirmado. Moeda não convertida fica separada e visível.
- Excluir pagamentos de fatura, transferências próprias, aportes e futuros do
  gasto realizado. Crédito/estorno permanece visível na auditoria.
- Recorrência é sugestão até confirmação; excluir parcelas da detecção.
- Falta de movimento não significa falha de sincronização. Posições antigas,
  intervalos desconhecidos e ausência de dados não são zero.
- Padrão temporal: último mês encerrado disponível; 12 meses de contexto;
  mês em curso compara o mesmo intervalo do anterior. Percentual sem base é
  “novo”; detalhamento mantém os mesmos filtros e moeda do total clicado.
- Publicação mantém última versão válida em falha. Escritas serializadas,
  operações em transações e origem/Host local validados.
- Sem publicação externa, novos frameworks, IA, metas ou orçamentos.

## Validação

Compra/fatura sem duplicidade; moedas distintas; 12 × R$ 100 versus uma compra
de R$ 1.200; classificação persistente e undo; regra prevista corresponde à
aplicada; parcelamento não vira assinatura; dados ausentes explícitos;
conciliação independente; teclado, celular e zoom 200%; suíte existente.
