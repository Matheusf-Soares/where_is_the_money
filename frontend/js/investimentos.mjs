// Investimentos: posições retratadas pela fonte, composição da carteira e os
// aportes e resgates que as regras de aplicação reconheceram no extrato.
// Nenhum valor é estimado: rendimento e valor aplicado só aparecem quando a
// instituição informou; o resto é "Não informado".
import * as C from './core.mjs';
import * as U from './ui.mjs';
const e=C.escapeHTML;
const TIPOS={EQUITY:'Renda variável',FIXED_INCOME:'Renda fixa',MUTUAL_FUND:'Fundo de investimento',SECURITY:'Previdência',ETF:'ETF',COE:'COE',OTHER:'Outros'};
const SUBTIPOS={STOCK:'Negociado em bolsa',CDB:'CDB',LCI:'LCI',LCA:'LCA',LC:'LC',CRI:'CRI',CRA:'CRA',DEBENTURES:'Debênture',TREASURY:'Tesouro Direto',INVESTMENT_FUND:'Fundo',MULTIMARKET_FUND:'Fundo multimercado',FIXED_INCOME_FUND:'Fundo de renda fixa',STOCK_FUND:'Fundo de ações',ETF:'ETF',REAL_ESTATE_FUND:'Fundo imobiliário'};
const rotuloTipo=r=>TIPOS[r.tipo]??r.tipo??'Não informado';
const rotuloSubtipo=r=>SUBTIPOS[r.subtipo]??r.subtipo??'';
const taxa=r=>r.taxa==null?'':String(r.tipo_taxa||'').toUpperCase()==='CDI'?`${C.numero(r.taxa)}% do CDI`:`${C.numero(r.taxa)}%${r.tipo_taxa?' '+r.tipo_taxa:''}`;
const quantidade=v=>v==null?'—':Number(v).toLocaleString('pt-BR',{maximumFractionDigits:8});
const preco=r=>r.saldo!=null&&r.quantidade?r.saldo/r.quantidade:null;

export function telaInvestimentos(ctx){
 const {estado,dados}=ctx,fs=estado.filtros;
 const todas=fs.conta?[]:C.filtrar(dados.stg_investimentos??[],{banco:fs.banco},false);
 const posicoes=C.posicoesEm(todas,fs.fim,'id_investimento');
 const ativas=posicoes.filter(r=>!r.posicao_ausente&&Number(r.saldo)>0);
 const zeradas=posicoes.filter(r=>r.posicao_ausente||!(Number(r.saldo)>0));
 const emBRL=ativas.filter(r=>r.moeda==='BRL'),outras=ativas.filter(r=>r.moeda!=='BRL');
 const total=C.somar(emBRL,'saldo');
 const serie=C.serieComparavel([],todas).filter(s=>s.data<=fs.fim);
 const anterior=serie.length>=2?serie.at(-2):null,atual=serie.at(-1)??null;
 const base=serie[0]??null;
 const naData=(id,data)=>todas.find(r=>r.id_investimento===id&&r.data_posicao===data);
 const maior=[...emBRL].sort((a,b)=>b.saldo-a.saldo)[0];
 const verPosicoes=data=>U.abrirDialog('Carteira em '+C.dataBR(data),U.tabela(['Ativo','Instituição',{n:'Quantidade'},{n:'Saldo'}],todas.filter(r=>r.data_posicao===data).map(r=>[e(r.nome),U.bancoNome(r.instituicao),quantidade(r.quantidade),U.celula(r.saldo==null?'Não disponível':C.brl(r.saldo),r.saldo)]),'',{rodape:['Total','','',C.brl(C.somar(todas.filter(r=>r.data_posicao===data&&r.moeda==='BRL'),'saldo'))]}));
 const verAtivo=id=>{const hist=todas.filter(r=>r.id_investimento===id).sort((a,b)=>a.data_posicao.localeCompare(b.data_posicao)),r=hist.at(-1);U.abrirDialog(r.nome,`<div class="detalhe-topo">${U.avatar(r.nome)}<span class="detalhe-valor">${C.brl(r.saldo)}</span><p>${e(rotuloTipo(r))}${rotuloSubtipo(r)?' · '+e(rotuloSubtipo(r)):''} · ${e(r.instituicao)}</p>${r.emissor?`<p>${e(r.emissor)}</p>`:''}</div>`+U.tabela(['Retrato',{n:'Quantidade'},{n:'Preço'},{n:'Saldo'}],hist.map(h=>[U.celula(C.dataBR(h.data_posicao),h.data_posicao),quantidade(h.quantidade),U.celula(preco(h)==null?'—':C.brl(preco(h)),preco(h)),U.celula(C.brl(h.saldo),h.saldo)])));};

 const variacaoTotal=anterior&&atual?C.variacao(atual.total,anterior.total):null;
 const faixa=`<div class="cards">${U.metrica('Valor em investimentos',C.brl(total),ativas[0]?`Retrato de ${C.dataBR(ativas.map(r=>r.data_posicao).sort().at(-1))}${outras.length?' · '+outras.length+' em outra moeda fora da soma':''}`:'Sem posição até esta data')}${U.metrica('Variação desde o retrato anterior',variacaoTotal?C.brl(variacaoTotal.delta):'Sem comparação',variacaoTotal?`${variacaoTotal.rotulo} · ${C.dataBR(anterior.data)} → ${C.dataBR(atual.data)}`:'Precisa de dois retratos completos',variacaoTotal?(variacaoTotal.delta>=0?'mint':'red'):'')}${U.metrica('Ativos com saldo',C.numero(ativas.length),`${C.numero(new Set(ativas.map(r=>r.instituicao)).size)} ${new Set(ativas.map(r=>r.instituicao)).size===1?'instituição':'instituições'}`)}${U.metrica('Maior posição',maior?maior.nome:'Sem dados',maior&&total?`${C.brl(maior.saldo)} · ${C.numero(Math.round(maior.saldo/total*100))}% da carteira`:'','word',maior?()=>verAtivo(maior.id_investimento):null)}</div>`;

 const grupos=(campo,rotulo)=>{const m=new Map();for(const r of emBRL){const k=rotulo(r);m.set(k,(m.get(k)??0)+Number(r.saldo));}return [...m].map(([nome,v])=>({nome,total:v})).sort((a,b)=>b.total-a.total);};
 const lista=gs=>`<div class="composicao-lista">${gs.map(g=>`<div class="composicao-item"><span>${e(g.nome)}</span>${U.quota(g.total,total)}<strong>${C.brl(g.total)}</strong></div>`).join('')}</div>`;
 const porAtivo=[...emBRL].sort((a,b)=>b.saldo-a.saldo).map(r=>({nome:r.nome,total:Number(r.saldo),id:r.id_investimento}));
 const composicao=U.painel('Composição da carteira',`${C.numero(emBRL.length)} ativos em BRL, do maior para o menor. Clique num ativo para ver seus retratos.`,U.barras(porAtivo,g=>verAtivo(g.id),12)+(porAtivo.length>12?`<p class="sub">Mais ${C.numero(porAtivo.length-12)} ativos na tabela de posições.</p>`:''));
 const distribuicao=U.painel('Por tipo e instituição','Classificação como a instituição informou.',`<h3 class="subtitulo">Tipo</h3>${lista(grupos('tipo',r=>rotuloTipo(r)+(rotuloSubtipo(r)?' · '+rotuloSubtipo(r):'')))}<h3 class="subtitulo">Instituição</h3>${lista(grupos('instituicao',r=>r.instituicao))}`);
 const evolucao=U.painel('Evolução da carteira','Somente retratos completos em BRL, com o mesmo conjunto de ativos. Clique num ponto para ver a carteira daquele dia.',serie.length<2?U.vazio('Ainda não há dois retratos completos para mostrar uma evolução.'):U.graficoLinha(serie.slice(-24),verPosicoes));

 const linhas=[...emBRL,...outras].sort((a,b)=>(b.saldo??0)-(a.saldo??0)).map(r=>{
  const inicio=base?naData(r.id_investimento,base.data):null;
  const mudouQtd=inicio&&Number(inicio.quantidade)!==Number(r.quantidade);
  const v=inicio&&base.data!==r.data_posicao?C.variacao(Number(r.saldo),Number(inicio.saldo)):null;
  const detalhes=[r.instituicao,rotuloSubtipo(r)||rotuloTipo(r),r.emissor,taxa(r),r.data_vencimento?'vence '+C.dataBR(r.data_vencimento):''].filter(Boolean).map(e).join(' · ');
  return [U.celula(`<div class="desc">${U.avatar(r.nome)}<div>${U.botao(e(r.nome),()=>verAtivo(r.id_investimento),'link')}<small>${detalhes}</small></div></div>`,r.nome),
   U.celula(quantidade(r.quantidade),r.quantidade),
   U.celula(preco(r)==null?'—':C.brl(preco(r)),preco(r)),
   U.celula(`<span class="valor-cell">${r.moeda==='BRL'?C.brl(r.saldo):e(r.moeda)+' '+C.numero(r.saldo)}</span>`,r.saldo),
   U.celula(r.moeda==='BRL'?U.quota(r.saldo,total):'—',r.saldo),
   U.celula(v?U.delta(v,{subirEBom:true})+(mudouQtd?'<small>quantidade mudou</small>':''):'—',v?.delta??null),
   U.celula(r.rendimento==null?'<span class="status">Não informado</span>':C.brl(r.rendimento),r.rendimento)];
 });
 const tabela=U.painel('Posições',`Retrato mais recente até ${C.dataBR(fs.fim)}.${base?` Variação contra ${C.dataBR(base.data)}, o primeiro retrato completo.`:''}`,U.tabela(['Ativo',{n:'Quantidade'},{n:'Preço'},{n:'Saldo'},{n:'Participação',alinhar:'esquerda'},{n:'Variação'},{n:'Rendimento'}],linhas,'tabela-carteira',{rodape:[outras.length?'Total BRL parcial':'Total da carteira','','',C.brl(total),total?'100%':'—','','']}));

 const movs=C.filtrar(dados.transacoes_analiticas??[],fs).filter(r=>r.motivo_exclusao==='aplicacao');
 const saidas=movs.filter(r=>r.valor_assinado<0),entradas=movs.filter(r=>r.valor_assinado>0);
 const aportes=U.painel('Aportes e resgates',`${C.dataBR(fs.inicio)} a ${C.dataBR(fs.fim)} · reconhecidos pelas regras de aplicação do regras.toml`,movs.length?U.tabela(['Data','Descrição','Direção',{n:'Valor'}],movs.sort((a,b)=>b.data.localeCompare(a.data)).map(r=>[U.celula(C.dataBR(r.data),r.data),U.celula(`<div class="desc">${U.avatar(r.instituicao,'bank-avatar')}<div>${U.botao(e(r.descricao),()=>ctx.detalhe(r),'link')}<small>${e(r.instituicao)} · ${e(r.conta||'')}</small></div></div>`,r.descricao),r.valor_assinado<0?U.pilula('Saída para investimento','acento'):U.pilula('Volta do investimento','pos'),U.celula(`<span class="valor-cell">${C.brl(r.valor_brl)}</span>`,r.valor_brl)]),'',{rodape:[['Total que saiu para investimentos','','',C.brl(C.somar(saidas))],['Total que voltou dos investimentos','','',C.brl(C.somar(entradas))]]}):U.vazio('Nenhum aporte ou resgate reconhecido neste período.'));

 const encerradas=zeradas.length?`<details class="panel recolhivel"><summary><div class="panel-head"><div><h2>Posições encerradas</h2><p class="sub">Ativos que já existiram na carteira e hoje estão zerados ou sem retrato · ${C.numero(zeradas.length)}</p></div>${U.icone('abrir')}</div></summary><div class="conteudo">${U.tabela(['Ativo','Instituição','Último retrato',{n:'Saldo'}],zeradas.map(r=>{const ult=todas.filter(x=>x.id_investimento===r.id_investimento).sort((a,b)=>b.data_posicao.localeCompare(a.data_posicao))[0];return [U.celula(`${e(r.nome)}<small>${e([rotuloSubtipo(r)||rotuloTipo(r),r.data_vencimento?'venceu '+C.dataBR(r.data_vencimento):''].filter(Boolean).join(' · '))}</small>`,r.nome),U.bancoNome(r.instituicao),U.celula(C.dataBR(ult?.data_posicao),ult?.data_posicao),U.celula(r.posicao_ausente?'Sem retrato até esta data':C.brl(r.saldo),r.saldo)];}))}</div></details>`:'';

 const avisos=(fs.conta?U.aviso('A fonte não liga investimentos a uma conta. Com um filtro de conta, esta tela fica vazia; limpe o filtro de conta para ver a carteira.',true):'')
  +U.aviso('Rendimento e valor aplicado só aparecem quando a instituição informa. Para ações e cotas a fonte não manda nenhum dos dois; a variação mostrada é a diferença de saldo entre retratos.',true);
 return faixa+`<div class="grid2 grid-largo">${composicao}${distribuicao}</div>`+evolucao+tabela+aportes+encerradas+avisos;
}
