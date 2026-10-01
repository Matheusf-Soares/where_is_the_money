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

Cada tela mostra primeiro a resposta (um número ou uma lista ordenada), depois o
que mudou ou o que falta conferir, e por último o grão da transação.

- **Resumo:** total, comparação temporal, categorias, meses e instituições.
- **Explorar gastos:** busca e total do recorte no topo; categorias com
  participação, variação e a faixa dos últimos 12 meses (cada mês clicável);
  estabelecimentos com ticket médio; transações com seleção para classificar.
- **Bancos e cartões:** gasto por instituição com estado da sincronização e
  última transação; contas monitoradas; categoria × banco; cobertura.
  Sincronização e última transação são informações diferentes.
- **Faturas:** valores oficiais por banco, cartões e Total clicáveis. Abre com o
  Total selecionado. O seletor próprio oferece a prévia em andamento e meses
  pelo **vencimento**, não pela data da compra; o histórico por vencimento
  compara os totais oficiais e também escolhe o mês. Os detalhes incluem todos
  os lançamentos vinculados à fatura e ao cartão pela fonte, inclusive créditos
  e compras de outro mês.
- **Recorrências e parcelas:** custo fixo confirmado e quantas sugestões esperam
  decisão; confirmadas ao lado do calendário de parcelas futuras (limitado ao
  que a fonte informou); fila de sugestões; ignoradas e encerradas recolhidas.
- **Patrimônio:** líquido e variação desde o primeiro retrato completo, ativos ×
  dívida na mesma escala, série e posições por conta/investimento e moeda. Série
  apenas quando existem ao menos dois retratos completos com composição comparável.
- **Investimentos:** valor da carteira e variação desde o retrato anterior;
  composição por ativo, por tipo e por instituição; evolução entre retratos
  completos; posições com quantidade, preço, saldo, participação e variação;
  aportes e resgates reconhecidos pelas regras de aplicação; posições encerradas.
  Rendimento e valor aplicado só aparecem quando a fonte informa.
- **Revisão:** caixa de entrada do que falta (sem classificação, códigos Pluggy
  sem associação, parcelas sem compra) e contagens nas abas; classificações e
  atributos em lote com desfazer, catálogo, associações Pluggy, aliases, regras
  com prévia, compras e auditoria.
- **Ferramentas SQL:** esquema com contagem de linhas, exemplos prontos, Ctrl+Enter
  para executar e até 500 linhas exibidas com o tempo da consulta. Os filtros do
  topo ficam escondidos: a bancada não os aplica.

O detalhe de um lançamento abre numa gaveta lateral, agrupado em classificação,
lançamento, valores, inclusão no gasto, parcelamento e identificadores.

O botão **?** no topo, ao lado da data da publicação (ou a tecla `?`), abre a ajuda da tela
atual: para que ela serve, como usar, o que é cada parte e como ela se liga às
outras telas. Enquanto aberta, cada parte explicada ganha um número na própria
tela; passar o mouse numa entrada contorna o elemento correspondente. A partir de
1440px o painel empurra o conteúdo; abaixo disso, sobrepõe.

Os filtros globais persistem entre telas; Faturas usa seu seletor de prévia em andamento ou mês de vencimento.
No Resumo, clicar numa coluna do gráfico mensal filtra a tela pelo mês escolhido.
Os demais gráficos abrem seus lançamentos e o
botão de voltar restaura a análise anterior. O modo por compra usa a view
`compras`: não agrupa parcelas por semelhança. A revisão de compras inclui futuros
e todo o histórico, explicitamente identificados na tela.

## Organização

- `js/core.mjs`: períodos, filtros comuns, formatação, grupos, posições e guarda SQL.
- `js/dados.mjs`: DuckDB-WASM, manifesto e troca de conexão; API de personalizações.
- `js/ui.mjs`: componentes acessíveis, escape HTML e delegação de ações.
- `js/app.mjs`: estado compartilhado, navegação, análises e detalhes.
- `js/revisao.mjs`: classificações, regras, catálogo, compras e auditoria.
- `js/faturas.mjs`: meses de vencimento, valores por banco e detalhes das faturas.
- `js/investimentos.mjs`: carteira, composição, posições e aportes e resgates.
- `js/ajuda.mjs`: painel de ajuda contextual e marcadores numerados sobre a tela.
- `js/ajuda-conteudo.mjs`: o texto da ajuda, por tela e aba, como dados puros.
- `js/icones.mjs`: ícones SVG de traço único usados na navegação e nas ações.
- `styles.css`: sistema visual (tokens de cor, tipografia Geist com algarismos
  tabulares, componentes), layout responsivo e estados de foco. A fonte Geist
  vem do jsDelivr; sem rede, a interface cai na fonte do sistema.

Views publicadas definem gasto, categoria e compra. Os relatórios carregam a
publicação completa na memória e aplicam o mesmo filtro comum às linhas e seus
detalhamentos. Não há consultas à Pluggy durante edições. Valores DECIMAL são
convertidos explicitamente a DOUBLE na view do navegador; ausências ficam nulas.

A API local usa token, revisão e origem. Uma resposta 202 indica que a correção
já foi salva: a interface oferece **Publicar novamente**, sem repetir a mutação.
Um conflito 409 exige recarga explícita. Sem API, relatórios permanecem acessíveis
e as edições mostram sua indisponibilidade.

Em Faturas, **Atualizar faturas** consulta a fonte configurada e republica os
dados. Para consultar a Pluggy com as credenciais locais, inicie com
`python -m financas servir --modo online`; o modo offline usa fixtures de teste.
A disponibilidade depende do banco/conector. Faturas ausentes aparecem
como “Não informada”; moedas sem conversão ficam separadas e o total BRL é
parcial. O valor oficial da fatura não representa o saldo restante após
pagamentos. Se faltarem vínculos ou a soma dos lançamentos diferir do total, o
detalhe informa a limitação, sem associar compras por aproximação. Consultas
anteriores permanecem disponíveis em caso de falha de atualização.

## Verificação

```powershell
node --test frontend/tests/*.test.mjs
node --check frontend/js/app.mjs
node --check frontend/js/revisao.mjs
node --check frontend/js/ajuda.mjs
```

Os testes são sintéticos e verificam períodos parciais/fechados, filtros e aspas,
valores ausentes, compras, snapshots comparáveis, SQL de leitura e revisão da API. `ajuda.test.mjs` falha se a ajuda citar um
painel, métrica, seletor, tela ou aba que não existe mais: renomear um título em
`app.mjs` exige atualizar `ajuda-conteudo.mjs` junto.
Verificação visual e interações de edição devem usar uma publicação sintética.

## Prévia, datas e tabelas

Faturas abre em **Em andamento · prévia parcial**. As views SQL
`faturas_abertas` e `lancamentos_fatura_aberta` separam despesas menos créditos,
pagamentos, períodos futuros e vínculos incertos. A prévia nunca representa um
total oficial ou saldo de limite utilizado. Os meses continuam mostrando os
valores oficiais pelo vencimento. Cada cartão exibe a última movimentação e a
consulta disponível; a previsão de mês da fonte pode estar inconsistente.

`data_gasto` e os dias da semana vêm transformados do backend. Quando a data da
compra difere do lançamento, a tabela informa ambas. As colunas de dados têm
ordenação crescente/decrescente; datas e números usam chaves originais. Em tabelas
paginadas, todo o recorte é ordenado antes de selecionar a página. Ordenar tabelas
de edição preserva os campos preenchidos e as seleções.

Tabelas de despesas mostram um rodapé Total separado por **18 px**, fora da
ordenação, que considera todo o recorte filtrado. Valores estrangeiros sem
conversão aparecem separadamente; percentuais e médias não são somados.
Os módulos `tabelas.mjs`, `extrato-fatura.mjs` e `faturas-abertas.mjs` concentram
respectivamente esses comportamentos compartilhados e a prévia.
