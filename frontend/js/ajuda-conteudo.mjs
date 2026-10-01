// Conteúdo da ajuda contextual: dados puros, sem DOM, para o teste importar.
//
// Cada item pode apontar para o elemento que a tela já desenha:
//   {painel:'Título'}  -> section.panel cujo h2 é exatamente esse título
//   {metrica:'Rótulo'} -> article.metric cujo rótulo é exatamente esse
//   {css:'seletor'}    -> primeiro elemento visível (aceita lista de alternativas)
// Um título renomeado em app.mjs faria a ajuda apontar para o nada sem aviso;
// tests/ajuda.test.mjs confere que cada título e seletor citado ainda existe.
//
// Campos de item: id, titulo, alvo, texto (string ou lista de parágrafos),
// termos ([[termo, definição]]), quando (mostrado se o alvo não estiver na tela),
// ir ([[tela, aba]] que a entrada oferece abrir).

export const comum=[
 {id:'publicacao',titulo:'Data da publicação',alvo:{css:'#snapshot'},
  texto:['Os números vêm da última publicação: um retrato dos dados gerado no seu computador. Abrir uma tela não consulta os bancos. Em Faturas, o botão “Atualizar faturas” consulta a Pluggy explicitamente.','Para ver lançamentos novos, rode python -m financas ingerir, publique de novo e clique em “Atualizar dados”, no fim do menu lateral. Edições feitas em Revisão são publicadas na hora.']},
 {id:'filtros',titulo:'Filtros do topo',alvo:{css:['#filtros','.mobile-filters']},
  texto:'Continuam aplicados quando você troca de tela. Faturas tem seu próprio mês de vencimento e não usa o período nem o modo por compra do topo.',
  termos:[
   ['Mês','Atalho que preenche De e Até com o mês inteiro. O mês atual aparece como “em curso”.'],
   ['Período','O intervalo analisado, de uma data até a outra, com as duas incluídas.'],
   ['Banco e Conta','Restringem tudo a uma instituição ou a uma conta ou cartão. Trocar o banco limpa a conta.'],
   ['Visualização','“Por parcela” conta cada parcela no mês em que foi lançada. “Por compra” conta o valor inteiro uma única vez, na data da compra, para as compras que você confirmou em Revisão › Compras.']]},
 {id:'tabelas',titulo:'Ordenação, datas e totais',alvo:{css:'.table-wrap'},
  quando:'Disponível nas telas com tabelas.',
  texto:['Clique no título de uma coluna para ordenar; clique novamente para inverter. A seta indica a ordem. Nas transações paginadas, a ordenação considera todo o recorte.','O Total aparece abaixo dos lançamentos, separado por um espaço, e soma todo o recorte filtrado, inclusive outras páginas. Moedas sem conversão ficam separadas; médias e percentuais não são somados.','Data do gasto usa a data da compra quando fornecida; caso contrário, usa a do lançamento. Quando diferem, ambas aparecem. O dia da semana é calculado junto com os dados, antes da publicação.']},
 {id:'avisos',titulo:'Avisos acima do conteúdo',alvo:{css:'#notices:not(:empty)'},
  quando:'Aparece quando há algo a saber sobre o recorte, como mês em curso ou valores sem conversão.',
  texto:'Explicam limites do que você está vendo. Nenhum deles é erro seu.'}
];

// Explicação de cada aviso que app.mjs pode escrever em #notices; a ajuda mostra
// só os que estão na tela agora, identificados por um trecho do texto.
export const avisos=[
 {contem:'Período em curso',termo:'Período em curso',texto:'O período inclui o mês atual, que ainda recebe lançamentos: a instituição pode levar até um dia para enviá-los. A comparação usa o mesmo número de dias do mês anterior, para ser justa.'},
 {contem:'Total BRL parcial',termo:'Total BRL parcial',texto:'Alguns lançamentos em moeda estrangeira vieram sem valor em reais. Ficam fora do total em BRL, mas entram na contagem e mostram o valor original no detalhe.'},
 {contem:'Por compra ·',termo:'Por compra',texto:'Quantos lançamentos o modo por compra representa e quantas parcelas ainda não foram associadas a uma compra. “Revisar compras” abre a aba onde você faz essa associação.'},
 {contem:'atrás da revisão de edição',termo:'Publicação desatualizada',texto:'Os dados foram editados depois que esta página carregou, talvez em outra aba. Atualize antes de gravar, para não trabalhar sobre uma versão antiga.'},
 {contem:'ainda não foi publicada',termo:'Publicação pendente',texto:'A correção foi gravada, mas a publicação falhou. “Publicar novamente” tenta de novo sem repetir a alteração.'},
 {contem:'Outra edição alterou',termo:'Conflito de edição',texto:'Os dados mudaram desde que você carregou a página. Atualize e revise antes de salvar outra vez.'}
];

export const caminho=[
 {ir:['resumo'],texto:'Veja o total e o que mudou.'},
 {ir:['explorar','transacoes'],texto:'Abra os lançamentos por trás de um número.'},
 {ir:['revisao','pendencias'],texto:'Corrija categorias, crie regras e junte parcelas.'},
 {ir:['revisao','auditoria'],texto:'Confira que nada sumiu nem foi contado duas vezes.'}
];
export const outrosAngulos=['bancos','faturas','recorrencias','patrimonio','investimentos','sql'];

const origens=[
 ['Classificação manual','Você escolheu a categoria deste lançamento.'],
 ['Regra pessoal','Uma regra criada em Revisão › Regras e categorias.'],
 ['Regra de configuração','Uma regra do arquivo regras.toml.'],
 ['Mapeamento pessoal','A categoria da Pluggy associada por você a uma categoria sua.'],
 ['Mapeamento de configuração','A mesma associação, vinda do regras.toml.'],
 ['Sem classificação','Nenhuma das camadas acima se aplicou.']
];

export const telas={
 faturas:{
  pergunta:'Quais faturas vencem neste mês e quais lançamentos pertencem a cada cartão?',
  filtros:'Esta tela usa seu próprio seletor. Em andamento mostra uma prévia parcial dos lançamentos pendentes; os meses selecionam as faturas pelo vencimento informado pela instituição.',
  passos:['Escolha Em andamento ou um mês de vencimento. A tela abre com o Total selecionado: o detalhe já mostra os lançamentos de todos os cartões.','Confira o valor por banco. Na prévia ele é provisório; nos meses é o total informado pela instituição.','Clique em um banco para ver só os cartões dele. Clique no Total para reunir os bancos de novo.','Use o histórico por vencimento para comparar meses e abrir um deles.','Use Atualizar faturas para consultar a Pluggy e publicar os dados recebidos.'],
  itens:[
   {id:'fatura-periodo',titulo:'Fatura / mês de vencimento',alvo:{css:'#fatura-mes'},texto:'Em andamento abre a prévia parcial, sem inventar vencimento. Os meses selecionam as faturas pelo mês em que vencem. Uma compra de julho pode estar na fatura de agosto. Trocar a seleção limpa o detalhe anterior.'},
   {id:'fatura-bancos',titulo:'Faturas por banco',alvo:{css:'.faturas-lista'},texto:'Cada linha mostra as faturas dos cartões daquele banco no mês selecionado. Toda a linha, incluindo o valor, pode ser clicada. “Não informada” significa que a instituição ainda não forneceu a fatura; não significa valor zero.'},
   {id:'fatura-total',titulo:'Total das faturas',alvo:{css:'.fatura-total'},texto:'Nos meses, soma os totais oficiais disponíveis em reais. Em andamento, soma despesas conhecidas menos créditos, sem descontar pagamentos de faturas anteriores. A prévia é sempre parcial. Valores em outras moedas ficam separados. Clique para abrir todos os bancos.'},
   {id:'fatura-historico',titulo:'Histórico por vencimento',alvo:{css:'#conteudo .historico-faturas'},
    quando:'Aparece quando a publicação tem faturas com total oficial.',
    texto:'Soma dos totais oficiais de cada mês de vencimento, nos últimos 12 meses. Mostra se as faturas estão subindo ou caindo. Clique numa coluna para abrir aquele mês. Coluna hachurada é mês sem fatura informada, não fatura zerada.'},
   {id:'fatura-extrato',titulo:'Detalhes da fatura',alvo:{css:'#fatura-detalhes'},texto:['Nos meses, exibe todos os lançamentos vinculados à fatura pela instituição. Em andamento, mostra pendências do ciclo conhecido; pagamentos ficam em uma seção própria, assim como futuros e lançamentos de associação incerta. Clique na descrição para consultar o lançamento original.','A prévia pode omitir compras ainda não enviadas pela instituição. Previsões de mês inconsistentes são sinalizadas. Ela não usa o limite utilizado do cartão como valor da fatura.','O total oficial não calcula o saldo restante depois dos pagamentos. Uma diferença para a soma dos lançamentos pode envolver saldos anteriores, encargos ou dados incompletos. O sistema avisa a diferença e não cria lançamentos para fechá-la.']}
  ],
  ligacoes:[{ir:['bancos'],texto:'Compare o gasto e as posições de todas as contas da instituição.'},{ir:['revisao','classificacao'],texto:'Classifique os lançamentos dos cartões.'}]
 },
 resumo:{
  pergunta:'Quanto saiu no período, para onde foi e o que mudou em relação ao período anterior?',
  passos:[
   'Escolha o período nos filtros do topo. Ao abrir, a página mostra o último mês completo com dados.',
   'Leia os quatro números do alto: total, variação, maior categoria e o que ainda está sem categoria.',
   'Clique numa coluna do gráfico mensal para filtrar o Resumo; os demais valores e gráficos abrem os lançamentos correspondentes.',
   'Achou algo sem categoria ou mal classificado? Corrija em Revisão.'],
  itens:[
   {id:'gasto',titulo:'Gasto no período',alvo:{metrica:'Gasto no período'},
    texto:['Soma das despesas do período, em reais. Já ficam de fora pagamento de fatura, transferência entre suas contas, aplicações e parcelas que ainda vão vencer, para nada ser contado duas vezes.','Clique no valor para ver cada lançamento.'],
    ir:[['explorar','transacoes'],['revisao','auditoria']]},
   {id:'variacao',titulo:'Variação no período',alvo:{metrica:'Variação no período'},
    texto:['Diferença em reais entre este período e o anterior de mesmo tamanho. Fica verde quando o gasto caiu.','Se o período inclui o mês atual, a comparação usa os mesmos dias do mês anterior.'],
    termos:[['novo','Não havia gasto no período anterior.'],['sem dados comparáveis','Falta dado em um dos dois períodos. Ausência não é tratada como zero.']]},
   {id:'maior',titulo:'Maior categoria',alvo:{metrica:'Maior categoria'},
    texto:'A categoria que mais pesou e a fatia dela no total. Clique no nome para ver os lançamentos.'},
   {id:'sem',titulo:'Sem classificação',alvo:{metrica:'Sem classificação'},
    texto:['Quanto do gasto ainda não tem categoria, e a porcentagem de lançamentos já classificados.','Enquanto esse valor for alto, tudo que é por categoria conta só parte da história.'],
    ir:[['revisao','pendencias']]},
   {id:'meses',titulo:'Seu gasto ao longo dos meses',alvo:{painel:'Seu gasto ao longo dos meses'},
    texto:'Até 12 meses terminando no fim do período. A coluna destacada é o mês selecionado. Clique numa coluna para filtrar o Resumo pelo mês correspondente, mantendo os filtros de instituição, conta e visualização.',
    termos:[['k','Mil reais: 3k são cerca de R$ 3.000.'],['*','Mês em curso, ainda incompleto.'],['Barra listrada','Mês sem nenhum registro. É falta de dado, não gasto zero.']]},
   {id:'destino',titulo:'Para onde o dinheiro foi',alvo:{painel:'Para onde o dinheiro foi'},
    texto:['As oito maiores categorias do período, da maior para a menor. Clique numa barra para ver os lançamentos da categoria.','Quando há gasto sem categoria, aparece o botão “Revisar classificação”.']},
   {id:'mudou',titulo:'O que mudou',alvo:{painel:'O que mudou'},
    texto:['Cada categoria agora e no período anterior, ordenada pela maior mudança em reais, para cima ou para baixo. Coral indica aumento; verde, redução.','Participação é a fatia da categoria no total de agora.']},
   {id:'instituicao',titulo:'Visão por instituição',alvo:{painel:'Visão por instituição'},
    texto:['Quanto foi gasto em cada banco, pela instituição que emitiu o lançamento: uma compra no cartão conta para o banco do cartão, não para a conta que pagou a fatura.','Classificados mostra quanto dos lançamentos já tem categoria. Um banco monitorado sem gasto aparece como “Sem dados”.'],
    ir:[['bancos']]}],
  ligacoes:[
   {ir:['explorar','transacoes'],texto:'Todo clique em valor, barra ou coluna abre Explorar gastos já filtrado. “Voltar à análise” traz você de volta para cá, no mesmo ponto.'},
   {ir:['revisao','pendencias'],texto:'É onde o valor “Sem classificação” diminui: você classifica por estabelecimento, do maior valor para o menor.'},
   {ir:['bancos'],texto:'Detalha a visão por instituição: contas, cartões e se cada banco continua enviando dados.'},
   {ir:['recorrencias'],texto:'O Resumo mostra o que já saiu; Recorrências mostra o que tende a se repetir e as parcelas que ainda vão vencer.'}]
 },

 explorar:{
  pergunta:'Quais lançamentos formam este número?',
  passos:[
   'Chegue aqui clicando em algo em outra tela, ou abra direto pelo menu.',
   'Escolha a aba: Categorias para ver grupos, Estabelecimentos para ver onde você comprou, Transações para ver cada lançamento.',
   'Refine com a busca e a categoria, e clique em “Aplicar”. A faixa de números mostra o total do que sobrou.',
   'Abra um lançamento para ver, na gaveta lateral, de onde ele veio e por que tem essa categoria.'],
  itens:[
   {id:'drill',titulo:'Voltar à análise',alvo:{css:'#conteudo > div.toolbar'},
    quando:'Aparece quando você chega aqui por um clique em outra tela.',
    texto:'Mostra o recorte que você abriu, por exemplo uma categoria num mês. “Voltar à análise” retorna à tela anterior com os mesmos filtros, aba e página.'},
   {id:'abas',titulo:'Abas',alvo:{css:'#conteudo > .tabs'},
    texto:'Três formas de olhar o mesmo recorte. A aba muda a apresentação; os lançamentos são os mesmos.'},
   {id:'busca',titulo:'Busca, categoria e ordem',alvo:{css:'#explore-form'},
    texto:['A busca procura o texto na descrição e no nome do estabelecimento, sem diferenciar maiúsculas. Os campos só valem depois de “Aplicar”; “Limpar” desfaz a busca e a categoria.','Esses campos refinam só esta tela. Os filtros do topo continuam valendo.']},
   {id:'faixa',titulo:'Total do recorte',alvo:{metrica:'Total do recorte'},
    texto:['A soma em reais de tudo o que a busca e os filtros deixaram, com a média por registro e o maior lançamento. Clique no maior lançamento para abrir o detalhe.','Fora de um recorte aberto por clique, o último número compara com o período anterior de mesmo tamanho.']},
   {id:'recorte',titulo:'Contagem e total do recorte',alvo:{css:'#explorar-painel > section.panel'},
    texto:'O título diz o que está sendo mostrado. Logo abaixo: quantos registros, a soma em reais e se a contagem é por parcela ou por compra.'}],
  abas:{
   categorias:{nome:'Categorias',itens:[
    {id:'barras',titulo:'Categorias no recorte',alvo:{painel:'Categorias no recorte'},
     texto:['Todas as categorias do recorte, da maior para a menor, com a fatia de cada uma no total e a variação contra o período anterior. Clique no nome para listar os lançamentos dela.','A variação sobe em coral e cai em verde. “sem dados comparáveis” quer dizer que não houve registro no período anterior.']},
    {id:'matriz',titulo:'Últimos 12 meses',alvo:{css:'#conteudo .heat-strip'},
     texto:['Cada quadrado é um dos últimos 12 meses, terminando no fim do período, mesmo que o período escolhido seja menor. Quanto mais forte o azul, maior o gasto da categoria naquele mês, comparado aos outros meses da mesma categoria.','Serve para achar o mês fora do padrão. Clique num quadrado para abrir exatamente aqueles lançamentos.'],
     termos:[['Quadrado hachurado','Nenhum registro naquele mês.'],['Traço azul embaixo','O mês em que o período termina.']]}]},
   estabelecimentos:{nome:'Estabelecimentos',itens:[
    {id:'lugares',titulo:'Estabelecimentos',alvo:{painel:'Estabelecimentos no recorte'},
     texto:['Onde o dinheiro foi gasto, somado por estabelecimento, do maior para o menor, com quantas vezes você comprou ali, o ticket médio e a fatia no total. Abaixo do nome, a categoria mais frequente. Clique no nome para ver os lançamentos.','O nome vem da descrição do extrato. Se o mesmo lugar aparece com nomes diferentes, padronize em Revisão › Regras e categorias.'],
     ir:[['revisao','regras']]}]},
   transacoes:{nome:'Transações',itens:[
    {id:'selecao',titulo:'Classificar selecionadas',alvo:{css:'#conteudo .selection'},
     texto:['Marque as caixas na tabela, escolha uma categoria e clique em “Classificar selecionadas”. A quantidade e a soma do que está marcado aparecem à esquerda.','Classificação manual vence qualquer regra. “Desfazer classificação” devolve os lançamentos marcados à categoria anterior.','Se os botões estiverem desativados, a edição local não está disponível: abra a página com python -m financas servir.']},
    {id:'lista',titulo:'Lista de lançamentos',alvo:{css:'#conteudo .table-wrap:has(> .tx-table)'},
     texto:['Um lançamento por linha. Abaixo da data: o dia da semana. Abaixo da descrição: banco, conta e, quando for o caso, a parcela ou a marca “futura”. Abaixo da categoria: a macro categoria e quem decidiu a categoria.','Quando mais de uma camada se aplica, vale a primeira desta lista:'],
     termos:origens},
    {id:'detalhe',titulo:'Detalhes de um lançamento',
     texto:'Clique na descrição ou na seta do fim da linha para abrir a gaveta lateral com tudo o que se sabe do lançamento, agrupado em classificação, lançamento, valores, inclusão no gasto, parcelamento e identificadores. Nada ali é estimado; o que a fonte não enviou aparece como “Não informado”.'},
    {id:'paginas',titulo:'Páginas',alvo:{css:'#conteudo .pagination'},
     quando:'Aparece quando o recorte tem mais de 50 lançamentos.',
     texto:'A lista mostra 50 lançamentos por vez. A ordem vale para o recorte inteiro, não só para a página.'}]}
  },
  ligacoes:[
   {ir:['revisao','regras'],texto:'Classificou o mesmo estabelecimento várias vezes? Uma regra classifica os próximos sozinha.'},
   {ir:['revisao','classificacao'],texto:'A mesma lista, com os atributos de essencialidade e comportamento.'},
   {ir:['resumo'],texto:'De onde vem a maior parte dos cliques que abrem esta tela.'},
   {ir:['sql'],texto:'Quando a pergunta não cabe nas abas, a bancada consulta as mesmas tabelas.'}]
 },

 bancos:{
  pergunta:'Quanto saiu por banco e cartão, e cada um continua enviando dados?',
  passos:[
   'Compare o gasto de cada instituição na primeira tabela e veja, abaixo do nome, se a sincronização deu certo.',
   'Confira contas e cartões um a um em “Contas monitoradas”.',
   'Use “Banco × categoria” para ver em que cada instituição é usada.',
   'Antes de comemorar um número baixo, confira “Cobertura e atualização”: pode ser falta de dado, não economia.'],
  itens:[
   {id:'gastos',titulo:'Gastos por banco e cartão',alvo:{painel:'Gastos por banco e cartão'},
    texto:['Por instituição: gasto, fatia no total, variação contra o período anterior, quantidade, quanto já está classificado e a data da última transação recebida. Abaixo do nome, o estado da última sincronização, ou “Parou de atualizar” quando a última transação passou do limite de dias do regras.toml (a mesma regra do comando frescor). A coluna da última transação diz há quantos dias chegou o lançamento mais recente e fica em coral quando passou do limite.','Pagar a fatura não aparece como gasto do banco que pagou: a compra já foi contada no cartão.']},
   {id:'contas',titulo:'Contas monitoradas',alvo:{painel:'Contas monitoradas'},
    texto:['Uma linha por conta ou cartão: instituição, tipo, data da última posição, saldo, limite disponível e gasto no período. Clique no nome de uma conta para ver os lançamentos dela.','“Sem posição até esta data” quer dizer que não há retrato do saldo, não que o saldo seja zero.']},
   {id:'matriz',titulo:'Banco × categoria',alvo:{painel:'Banco × categoria'},
    texto:'Categorias nas linhas, instituições nas colunas. Mostra, por exemplo, qual banco concentra mercado ou transporte; quanto mais forte o azul, maior o valor. Cada valor abre seus lançamentos.'},
   {id:'cobertura',titulo:'Cobertura e atualização',alvo:{painel:'Cobertura e atualização'},
    texto:'Quatro informações que parecem iguais, mas dizem coisas diferentes:',
    termos:[
     ['Sincronização','Se a última busca de dados deu certo, e quando foi.'],
     ['Última transação','O lançamento mais recente que chegou.'],
     ['Posição','A data do último saldo registrado.'],
     ['Cobertura registrada','O intervalo de datas pedido à fonte.'],
     ['O sinal de alerta','Sincronização concluída com última transação antiga: tudo parece funcionar, mas nada novo chega. Costuma ser consentimento vencido; renove a autorização no Meu Pluggy e confira com python -m financas frescor.']]}],
  ligacoes:[
   {ir:['patrimonio'],texto:'Soma os saldos das contas e desconta a dívida dos cartões.'},
   {ir:['explorar','transacoes'],texto:'Todo valor clicado aqui abre a lista de lançamentos correspondente.'},
   {ir:['revisao','auditoria'],texto:'Mostra por que pagamentos de fatura e transferências não entram no gasto.'}]
 },

 recorrencias:{
  pergunta:'O que se repete todo mês, quanto custa por ano e o que já está comprometido?',
  filtros:'O período do topo não se aplica aqui: a detecção usa todo o histórico. Instituição e conta continuam valendo.',
  passos:[
   'Leia no alto o custo fixo confirmado e quantas sugestões esperam decisão.',
   'Em “Sugestões para revisar”, confirme o que é assinatura ou conta fixa e ignore o que foi coincidência.',
   'Acompanhe as confirmadas e encerre as que você cancelou.',
   'Consulte o calendário ao lado para saber quais parcelas ainda vão chegar.'],
  itens:[
   {id:'deteccao',titulo:'Como a detecção funciona',alvo:{css:'#conteudo > .section-note'},
    texto:'Um estabelecimento vira sugestão quando cobra em vários meses. Um mês sem cobrança não encerra nada: só você encerra. Parcelas ficam de fora, porque já têm fim conhecido.'},
   {id:'confirmadas-n',titulo:'Recorrências confirmadas',alvo:{metrica:'Recorrências confirmadas'},
    texto:'Quantas cobranças você confirmou como recorrentes e quanto custam por mês, em média.'},
   {id:'custo',titulo:'Custo anual estimado',alvo:{metrica:'Custo anual estimado'},
    texto:'Média mensal observada vezes 12, somando só as confirmadas. É uma ordem de grandeza, não uma previsão: reajustes e meses sem cobrança não entram na conta.'},
   {id:'revisar',titulo:'A revisar',alvo:{metrica:'A revisar'},
    texto:'Sugestões esperando sua decisão. Clique no número para ir até a lista.'},
   {id:'futuras',titulo:'Parcelas futuras conhecidas',alvo:{metrica:'Parcelas futuras conhecidas'},
    texto:'Soma das parcelas que as instituições já informaram e ainda não venceram. Não inclui compras novas.'},
   {id:'confirmadas',titulo:'Confirmadas',alvo:{painel:'Confirmadas'},
    texto:'O que você confirmou, com média mensal, estimativa anual e o intervalo de meses observados. “Encerrar no banco” registra que a cobrança acabou.'},
   {id:'sugestoes',titulo:'Sugestões para revisar',alvo:{painel:'Sugestões para revisar'},
    texto:['Padrões encontrados, ainda sem decisão. “Confirmar no banco” leva para Confirmadas; “Ignorar” tira da lista.','A decisão vale para o estabelecimento no banco inteiro, inclusive em outras contas e cartões do mesmo banco.']},
   {id:'ignoradas',titulo:'Ignoradas',alvo:{painel:'Ignoradas'},
    texto:'O que você marcou como não recorrente, recolhido no fim da tela. Clique no título para abrir. Dá para confirmar depois, se mudar de ideia.'},
   {id:'encerradas',titulo:'Encerradas',alvo:{painel:'Encerradas'},
    texto:'Recorrências que acabaram, recolhidas no fim da tela. Ficam como histórico e saem do custo anual.'},
   {id:'calendario',titulo:'Calendário futuro conhecido',alvo:{painel:'Calendário futuro conhecido'},
    texto:'Parcelas futuras por mês, como as instituições informaram, com uma barra proporcional ao valor. É incompleto por natureza: não inclui compras que você ainda vai fazer nem assinaturas. Clique num mês para listar as parcelas dele.'}],
  ligacoes:[
   {ir:['revisao','compras'],texto:'Juntar as parcelas numa compra faz o modo “Por compra” mostrar o valor inteiro na data da compra.'},
   {ir:['explorar','estabelecimentos'],texto:'Para conferir o histórico de um estabelecimento antes de confirmar.'},
   {ir:['resumo'],texto:'As cobranças recorrentes já estão no gasto do Resumo; aqui elas só aparecem agrupadas.'}]
 },

 patrimonio:{
  pergunta:'Quanto você tem, somando contas e investimentos e descontando os cartões?',
  filtros:'“Até” define a data das posições. Filtrar por conta esconde os investimentos, que não têm vínculo com conta na fonte.',
  passos:[
   'Ajuste “Até” nos filtros para ver as posições naquela data.',
   'Leia o patrimônio líquido, quanto ele mudou desde o primeiro retrato completo e, abaixo, as três partes que o compõem.',
   'Clique num ponto do histórico para ver cada posição daquela data.',
   'Se o total vier marcado como parcial, confira as tabelas para achar o que falta.'],
  itens:[
   {id:'calculo',titulo:'Como o total é calculado',alvo:{css:'#conteudo > .notice'},
    texto:'Contas bancárias mais investimentos menos a dívida dos cartões, em reais. Contas de investimento aparecem na lista, mas o saldo delas já está em Investimentos e não é somado de novo.'},
   {id:'liquido',titulo:'Patrimônio líquido',alvo:{metrica:['Patrimônio líquido monitorado','Patrimônio BRL parcial']},
    texto:'O resultado da conta acima. Quando vira “Patrimônio BRL parcial”, alguma posição está sem saldo, sem data ou em outra moeda, e o número fica menor que a realidade.'},
   {id:'composicao',titulo:'Ativos e dívida',alvo:{css:'#conteudo .composicao-barra'},
    texto:'Duas barras na mesma escala: ativos, divididos entre contas e investimentos, e a dívida dos cartões. Mostram de relance quanto do que você tem já está comprometido.'},
   {id:'caixa',titulo:'Saldo em contas bancárias',alvo:{metrica:'Saldo em contas bancárias'},
    texto:'Soma dos saldos das contas em reais. É dinheiro guardado, não gasto.'},
   {id:'investimentos',titulo:'Investimentos',alvo:{metrica:'Investimentos'},
    texto:'Soma das posições de investimento em reais, na data mais recente até “Até”.'},
   {id:'divida',titulo:'Dívida em cartões',alvo:{metrica:'Dívida em cartões'},
    texto:'Saldo devedor informado pelos cartões. É uma posição, não um gasto; por isso não precisa bater com o gasto do cartão no mês.'},
   {id:'historico',titulo:'Histórico de posições',alvo:{painel:'Histórico de posições'},
    texto:['Uma linha com o patrimônio nas datas em que todas as contas e investimentos foram retratados em reais. Datas incompletas ficam de fora, para a linha não cair só porque faltou uma conta.','Clique num ponto para ver as posições daquele dia. Com menos de dois retratos completos, o painel avisa que ainda não há tendência.']},
   {id:'contas',titulo:'Contas e cartões',alvo:{painel:'Contas e cartões'},
    texto:'Cada conta com tipo, data da posição, moeda, saldo original e limite disponível. “Posição anterior à data de referência” indica um saldo mais antigo que a publicação.'},
   {id:'aplicacoes',titulo:'Investimentos monitorados',alvo:{painel:'Investimentos monitorados'},
    texto:'Cada aplicação com duas datas: quando o dado foi capturado e a data de referência informada pela instituição. Valores em moedas diferentes não são somados.'}],
  ligacoes:[
   {ir:['investimentos'],texto:'A carteira em detalhe: cada ativo, sua participação e como variou entre os retratos.'},
   {ir:['bancos'],texto:'Mostra se cada instituição continua atualizando. Posição antiga pode ser consentimento vencido.'},
   {ir:['revisao','auditoria'],texto:'Aplicações e resgates ficam fora do gasto; a auditoria mostra quanto saiu do total por esse motivo.'},
   {ir:['sql'],texto:'As posições diárias podem ser consultadas nas tabelas stg_contas e stg_investimentos.'}]
 },

 investimentos:{
  pergunta:'Quanto está investido, onde está e como cada posição variou?',
  filtros:'“Até” define a data das posições e o período define os aportes e resgates listados. Banco filtra a carteira. A fonte não liga investimento a conta, então o filtro de conta esvazia a tela.',
  passos:[
   'Leia no alto o valor em investimentos e quanto ele mudou desde o retrato anterior.',
   'Veja em “Composição da carteira” onde o dinheiro está; clique num ativo para ver seus retratos.',
   'Use a tabela de posições para comparar quantidade, preço, saldo e variação de cada ativo.',
   'Confira em “Aportes e resgates” o dinheiro que saiu das contas para investir ou voltou delas.'],
  itens:[
   {id:'valor',titulo:'Valor em investimentos',alvo:{metrica:'Valor em investimentos'},
    texto:'Soma dos saldos em reais no retrato mais recente até “Até”. Ativos em outra moeda ficam fora da soma e são avisados.'},
   {id:'variacao',titulo:'Variação desde o retrato anterior',alvo:{metrica:'Variação desde o retrato anterior'},
    texto:'Diferença entre os dois últimos retratos completos da carteira. Inclui oscilação de preço e qualquer compra ou venda feita entre eles.'},
   {id:'ativos',titulo:'Ativos com saldo',alvo:{metrica:'Ativos com saldo'},texto:'Quantos ativos têm saldo hoje, e em quantas instituições.'},
   {id:'maior',titulo:'Maior posição',alvo:{metrica:'Maior posição'},texto:'O ativo que mais pesa na carteira e sua fatia. Clique para ver os retratos dele.'},
   {id:'composicao',titulo:'Composição da carteira',alvo:{painel:'Composição da carteira'},texto:'Os ativos do maior para o menor saldo. A barra mostra o peso de cada um na carteira.'},
   {id:'distribuicao',titulo:'Por tipo e instituição',alvo:{painel:'Por tipo e instituição'},
    texto:'A mesma carteira agrupada pelo tipo informado pela instituição e por onde o dinheiro está. Ações e cotas de fundos negociadas em bolsa chegam com o mesmo tipo; a tela não tenta separar umas das outras.'},
   {id:'evolucao',titulo:'Evolução da carteira',alvo:{painel:'Evolução da carteira'},
    texto:'O valor total em cada retrato completo. Datas em que faltou algum ativo ficam de fora, para a linha não cair só porque um retrato veio incompleto.'},
   {id:'posicoes',titulo:'Posições',alvo:{painel:'Posições'},
    texto:['Cada ativo com quantidade, preço (saldo dividido pela quantidade), saldo, participação e variação contra o primeiro retrato completo. Quando a quantidade mudou no meio, a variação inclui a compra ou a venda, e a linha avisa.','Rendimento só aparece quando a instituição informa. Para ações e cotas ela não informa, e a tela mostra “Não informado” em vez de inventar zero.']},
   {id:'aportes',titulo:'Aportes e resgates',alvo:{painel:'Aportes e resgates'},
    texto:'Transações das contas que as regras de aplicação do regras.toml reconheceram como ida ou volta de investimento, dentro do período. Ficam fora do gasto. Aporte feito por um caminho que nenhuma regra reconhece não aparece aqui.',
    ir:[['revisao','auditoria']]},
   {id:'encerradas',titulo:'Posições encerradas',alvo:{css:'#conteudo details.recolhivel'},quando:'Aparece quando algum ativo foi zerado ou deixou de ser retratado.',
    texto:'Ativos que já estiveram na carteira e hoje estão zerados, como um CDB vencido.'}],
  ligacoes:[
   {ir:['patrimonio'],texto:'Soma a carteira com as contas e desconta a dívida dos cartões.'},
   {ir:['revisao','auditoria'],texto:'Mostra quanto saiu do gasto por ser aplicação ou resgate.'},
   {ir:['sql'],texto:'As posições diárias estão em stg_investimentos.'}]
 },

 revisao:{
  pergunta:'Onde você corrige, classifica e confere os dados, sem mudar o que veio do banco.',
  passos:[
   {texto:'Comece por Pendências: o que está sem categoria, do maior valor para o menor.',ir:['revisao','pendencias']},
   {texto:'Classifique lançamento a lançamento, ou crie uma regra para todos de um estabelecimento.',ir:['revisao','regras']},
   {texto:'Junte as parcelas de uma mesma compra.',ir:['revisao','compras']},
   {texto:'Termine conferindo que nada sumiu nem foi contado duas vezes.',ir:['revisao','auditoria']}],
  itens:[
   {id:'abas',titulo:'Abas da revisão',alvo:{css:'#conteudo > .tabs'},
    texto:['As abas seguem a ordem natural do trabalho, da esquerda para a direita. O número ao lado de Pendências e Compras é quanto ainda falta em cada uma.','Toda alteração é gravada à parte e publicada de novo. O dado original do banco nunca muda; por isso tudo aqui pode ser desfeito.']}],
  abas:{
   pendencias:{nome:'Pendências',pergunta:'O que ainda está sem categoria, e por onde começar?',itens:[
    {id:'caixa',titulo:'O que falta revisar',alvo:{metrica:'Gasto sem classificação'},
     texto:'Três contagens do trabalho pendente: gasto sem categoria no período, códigos de categoria da Pluggy ainda sem associação e parcelas que não foram juntadas numa compra. Clique em “Parcelas sem compra” para ir à aba Compras.',
     ir:[['revisao','compras']]},
    {id:'atencao',titulo:'O que merece sua atenção',alvo:{painel:'O que merece sua atenção'},
     texto:['Gastos sem categoria no período, agrupados por estabelecimento e ordenados pelo valor. Comece pelo topo: poucos grupos costumam cobrir a maior parte do valor.','“Abrir grupo” lista os lançamentos em Explorar gastos, onde você marca e classifica.'],
     ir:[['explorar','transacoes']]},
    {id:'fonte',titulo:'Categorias da fonte sem associação',alvo:{painel:'Categorias da fonte sem associação'},
     texto:['Categorias que a Pluggy atribuiu, com o código de cada uma. Associe cada código a uma categoria sua e todo lançamento com ele passa a ser classificado, inclusive os que ainda vão chegar.','Quando o nome coincide, a sugestão já vem escolhida, mas só vale depois de “Aprovar associações selecionadas”.']}]},
   classificacao:{nome:'Classificação',pergunta:'Qual é a categoria certa de cada lançamento?',itens:[
    {id:'classificar',titulo:'Classificar lançamentos',alvo:{painel:'Classificar lançamentos'},
     texto:'Todos os gastos do período, com caixas de seleção. Marque, escolha a categoria na barra acima da tabela e clique em “Classificar selecionadas”. A classificação manual vence qualquer regra.'},
    {id:'atributos',titulo:'Finalidade e comportamento',alvo:{painel:'Finalidade e comportamento'},
     texto:['Dois atributos independentes da categoria, aplicados aos lançamentos marcados na tabela acima.','Nada é deduzido pelo estabelecimento: o mesmo mercado pode ser essencial numa compra e discricionário em outra.'],
     termos:[['Essencialidade','Essencial ou discricionário: se o gasto era necessário.'],['Comportamento','Fixo ou variável: se o valor se repete igual todo mês.']]}]},
   regras:{nome:'Regras e categorias',pergunta:'Como classificar automaticamente o que se repete?',itens:[
    {id:'categoria',titulo:'Nova categoria',alvo:{painel:'Nova categoria'},
     texto:'Cria uma categoria dentro de uma macro categoria, como Transporte / Aplicativos, com essencialidade e comportamento padrão.'},
    {id:'regra',titulo:'Nova regra',alvo:{painel:'Nova regra'},
     texto:['Classifica sozinha todo lançamento cuja descrição ou estabelecimento case com o padrão.','“Simular regra” mostra quantos lançamentos mudariam e quanto somam, antes de aplicar. Classificações manuais nunca são sobrescritas.'],
     termos:[['Padrão','Texto com % no lugar de qualquer trecho: %padaria% casa com “PADARIA CENTRAL LTDA”.'],['Instituição','O mesmo tipo de padrão. % vale para todas.'],['Prioridade','Quando duas regras casam, vence o menor número.']]},
    {id:'catalogo',titulo:'Catálogo de categorias',alvo:{painel:'Catálogo de categorias'},
     texto:'Todas as suas categorias. Editar muda nome e padrões; os lançamentos continuam ligados a ela.'},
    {id:'regras',titulo:'Regras da interface',alvo:{painel:'Regras da interface'},
     texto:['As regras criadas aqui, pela ordem de prioridade. Desativar guarda a regra, mas ela para de classificar.','Regras do arquivo regras.toml não aparecem nesta lista e valem depois destas.']},
    {id:'alias',titulo:'Padronizar estabelecimento',alvo:{painel:'Padronizar estabelecimento'},
     texto:'Dá um nome único a descrições diferentes do mesmo lugar. A descrição precisa ser exata, sem contar maiúsculas. A descrição original continua guardada.'},
    {id:'mapas',titulo:'Associações de categorias Pluggy',alvo:{painel:'Associações de categorias Pluggy'},
     texto:'A mesma associação da aba Pendências, reunida aqui com as outras formas de classificar.'}]},
   compras:{nome:'Compras',pergunta:'Quais parcelas pertencem à mesma compra?',itens:[
    {id:'historico',titulo:'Todo o histórico',alvo:{css:'#conteudo > .notice'},
     texto:'Esta aba ignora o período e mostra todo o histórico, inclusive parcelas futuras, porque uma compra parcelada atravessa meses. Instituição e conta continuam valendo.'},
    {id:'parcelas',titulo:'Parcelas aguardando associação',alvo:{painel:'Parcelas aguardando associação'},
     texto:'Parcelas ainda não ligadas a uma compra. Marque as parcelas de uma mesma compra, sempre da mesma conta. A soma do que está marcado aparece acima da tabela.'},
    {id:'confirmar',titulo:'Confirmar compra integral',alvo:{painel:'Confirmar compra integral'},
     texto:['Informe a data original, o valor total e uma descrição, e clique em “Associar compra confirmada”. No modo “Por compra”, o valor total passa a contar uma vez, nessa data.','Se algumas parcelas ainda não chegaram, marque a confirmação de que só parte está disponível.']},
    {id:'associadas',titulo:'Compras associadas',alvo:{painel:'Compras associadas'},
     texto:'As compras que você confirmou. “Desfazer associação” desfaz só o vínculo; os lançamentos continuam intactos.'}]},
   auditoria:{nome:'Auditoria',pergunta:'Algum lançamento sumiu ou foi contado duas vezes?',itens:[
    {id:'regra',titulo:'O que a auditoria usa',alvo:{css:'#conteudo > .notice'},
     texto:'Conta sempre por lançamento, mesmo no modo “Por compra”, e usa período, instituição e conta do topo.'},
    {id:'esperado',titulo:'Consumo esperado pelo extrato',alvo:{metrica:'Consumo esperado pelo extrato'},
     texto:'Soma das despesas calculada direto do extrato tratado, tirando só as exclusões explícitas.'},
    {id:'obtido',titulo:'Gasto na view analítica',alvo:{metrica:'Gasto na view analítica'},
     texto:'O mesmo total, calculado pelo caminho que alimenta as outras telas.'},
    {id:'diferenca',titulo:'Diferença de conciliação',alvo:{metrica:'Diferença de conciliação'},
     texto:'Deve ser zero, em verde. Em vermelho, os dois caminhos discordam: há lançamento a mais ou a menos em algum lugar.'},
    {id:'moedas',titulo:'Originais por moeda × BRL publicado',alvo:{painel:'Originais por moeda × BRL publicado'},
     texto:'Uma linha por moeda. Moedas diferentes nunca são somadas; o valor em reais só existe quando a fonte informou ou quando você confirmou uma compra.'},
    {id:'exclusoes',titulo:'Exclusões e créditos',alvo:{painel:'Exclusões e créditos'},
     texto:'Responde “por que esse gasto sumiu do total?”. Cada lançamento fora do gasto aparece uma única vez, no motivo que o tirou:',
     termos:[['Pagamentos de fatura','A compra já foi contada no cartão.'],['Transferências próprias','Dinheiro que mudou de conta sem sair do seu bolso.'],['Aplicações / resgates','Dinheiro indo para investimento ou voltando dele.'],['Pendentes reemitidas','A instituição lançou a transação pendente com um id novo; a pendente antiga sai para não contar duas vezes.'],['Saldo de fatura anterior','“Saldo em atraso” ou “em rotativo”: o restante da fatura anterior lançado de novo na seguinte. As compras já contaram quando aconteceram; juros e multa continuam no gasto.'],['Lançamentos futuros','Parcelas que ainda não venceram.'],['Entradas, estornos e sem valor','Créditos não são gastos.']]},
    {id:'semconversao',titulo:'Gastos sem conversão',alvo:{painel:'Gastos sem conversão'},
     texto:'Gastos em moeda estrangeira sem valor em reais. Contam na quantidade, mas não no total em BRL.'}]}
  },
  ligacoes:[
   {ir:['explorar','transacoes'],texto:'Classificar direto na lista de lançamentos tem o mesmo efeito da aba Classificação.'},
   {ir:['resumo'],texto:'Cada classificação é publicada na hora, e o valor “Sem classificação” do Resumo diminui.'},
   {ir:['recorrencias'],texto:'As parcelas do calendário futuro são as mesmas que você associa em Compras.'}]
 },

 sql:{
  pergunta:'Qual pergunta os painéis não respondem?',
  filtros:'Os filtros do topo ficam escondidos nesta tela, porque a bancada não os aplica. Escreva o recorte no próprio WHERE.',
  passos:[
   'Clique numa tabela à esquerda, ou num exemplo, para começar com uma consulta pronta.',
   'Ajuste a consulta. Só são aceitos SELECT, WITH, DESCRIBE e EXPLAIN.',
   'Clique em “Executar consulta” ou tecle Ctrl + Enter. Até 500 linhas aparecem abaixo, com o tempo da consulta.'],
  itens:[
   {id:'leitura',titulo:'Somente leitura',alvo:{css:'#conteudo > .notice'},
    texto:'Não há como alterar dados daqui, nem ler arquivos ou a internet. A consulta roda no seu navegador, sobre a publicação carregada.'},
   {id:'esquema',titulo:'Tabelas',alvo:{css:'#conteudo .esquema'},
    texto:'Todas as tabelas da publicação, com a quantidade de linhas de cada uma. Clicar numa delas preenche a consulta com as 100 primeiras linhas.'},
   {id:'bancada',titulo:'Bancada SQL',alvo:{painel:'Bancada SQL'},
    texto:'O editor da consulta e os exemplos prontos. As tabelas são as mesmas que alimentam as outras telas:',
    termos:[
     ['gastos_analiticos','Um gasto por linha, com a categoria resolvida. Base do Resumo e de Explorar gastos.'],
     ['transacoes_analiticas','Todos os lançamentos, inclusive os excluídos do gasto, com o motivo.'],
     ['compras','Uma linha por compra. Base do modo “Por compra”.'],
     ['recorrencias_analiticas','Base de Recorrências e parcelas.'],
     ['stg_contas e stg_investimentos','Posições diárias. Base de Patrimônio.'],
     ['qualidade_dados','Base de Cobertura e atualização, em Bancos e cartões.']]},
   {id:'resultado',titulo:'Resultado',alvo:{css:'#sql-result:not(:empty)'},
    quando:'Aparece depois de executar uma consulta.',
    texto:'As linhas devolvidas, até 500, com a contagem e o tempo da consulta. Se a consulta for recusada, a mensagem diz o que não é permitido.'}],
  ligacoes:[
   {ir:['explorar','transacoes'],texto:'Para ver e classificar os lançamentos que a consulta encontrou.'},
   {ir:['revisao','auditoria'],texto:'A conciliação entre extrato e gasto, pronta, sem escrever SQL.'}]
 }
};
