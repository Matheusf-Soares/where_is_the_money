---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: []
---

# Frontend de investigação · surface brief

Escopo: aplicação inteira em `frontend/` (oito telas, ajuda, diálogo de detalhe).
Modo: **Operate**. Usuário único, técnico, abre a ferramenta no fim do dia para
entender para onde o dinheiro foi e conferir se os dados estão completos.

Decisões do usuário (01/10/2026): padrão da categoria escolhido de propósito;
régua de acabamento **Mercury**; Resumo mantém estrutura e recebe só o visual;
ajuda mantida, com cor própria adaptada ao novo sistema.

## Direction contract

THESIS: o dashboard financeiro escuro da categoria, executado no nível do
Mercury: sóbrio, denso onde o dado pede, cada número abre o lançamento que o
compõe. Recusa a colcha de cartões com borda verde-menta, sobrancelhas em caixa
alta e glifos Unicode no lugar de ícones.

OWN-WORLD: grafite frio em três camadas (fundo, superfície, elevado), linhas
finas de 1px, um único azul de ação para seleção, links e série principal;
verde e coral só para entrada/saída e alerta, âmbar só para dado parcial.
Geist com algarismos tabulares, escala fixa de nove passos (12–34px). Ícones SVG de traço único.
Filtros como chips; detalhe abre numa gaveta lateral, não num modal central.

STORY: o usuário vê primeiro a resposta da tela (um número ou uma lista
ordenada), depois o que mudou ou o que falta conferir, e por último a tabela
de grão de transação. Cada agregado leva ao seu recorte.

FIRST VIEWPORT: barra lateral fixa à esquerda com navegação agrupada e
frescor da publicação; no topo, título da tela, linha de propósito e chips de
filtro; abaixo, a faixa de resposta da tela (KPIs ou lista principal) ocupando
a largura, seguida do painel dominante. Ação primária de cada tela no
cabeçalho do seu painel.

FORM: canon (padrão da categoria), escolhido pelo usuário na rodada de direção;
seed key c8770694.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Planejamento por tela

- **Explorar gastos.** Primeiro: a busca e o total do recorte. Depois: categorias
  ordenadas com participação, variação e a faixa dos 12 meses clicável por mês.
  Por último: estabelecimentos e transações com seleção para classificar.
- **Bancos e cartões.** Primeiro: um bloco por instituição com gasto, participação,
  variação e frescor do dado. Depois: contas e posições. Por último: banco ×
  categoria e a tabela de cobertura.
- **Faturas.** Primeiro: quanto está em aberto ou quanto vence no mês, total e
  por banco. Depois: o extrato do banco escolhido. Por último: histórico dos
  totais oficiais por vencimento, que também escolhe o mês.
- **Recorrências e parcelas.** Primeiro: custo fixo confirmado e quantas sugestões
  esperam revisão. Depois: confirmadas e o calendário de parcelas futuras.
  Por último: fila de sugestões; ignoradas e encerradas recolhidas.
- **Patrimônio.** Primeiro: patrimônio líquido e sua série. Depois: composição
  entre contas, investimentos e dívida. Por último: tabelas por conta e por
  investimento.
- **Revisão.** Primeiro: a caixa de entrada com o que falta (sem classificação,
  categorias sem associação, parcelas sem compra). Depois: o trabalho de cada
  aba. Contagens nas abas.
- **Ferramentas SQL.** Primeiro: o editor pronto, com o esquema ao lado. Depois:
  resultado com contagem e tempo. Ctrl+Enter executa.

## Em aberto

- Nenhum dado real em capturas compartilhadas fora da máquina.
