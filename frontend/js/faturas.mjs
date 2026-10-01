// Faturas são selecionadas pelo vencimento e vinculadas pelo identificador da fonte.
import * as C from './core.mjs';
import * as U from './ui.mjs';
import {telaAndamento} from './faturas-abertas.mjs';
import {tabelaExtrato} from './extrato-fatura.mjs';
const e=C.escapeHTML;
const chave=f=>JSON.stringify([f.id_conta,f.id_fatura]);
const nomeMes=mes=>new Date(mes+'-01T12:00:00Z').toLocaleDateString('pt-BR',{month:'long',year:'numeric',timeZone:'UTC'});
const dinheiro=(valor,moeda='BRL')=>valor===null||valor===undefined?'Não informada':moeda==='BRL'?C.brl(valor):`${e(moeda)} ${C.numero(valor)}`;

export function dataAtualFaturas(agora=new Date()){return `${agora.getFullYear()}-${String(agora.getMonth()+1).padStart(2,'0')}-${String(agora.getDate()).padStart(2,'0')}`;}

export function mesesFaturas(faturas,referencia){
 const atual=referencia.slice(0,7);
 const meses=new Set([...C.mesesContexto(referencia),...faturas.map(f=>f.mes_referencia||String(f.vencimento).slice(0,7))]);
 return [...meses].filter(m=>/^\d{4}-\d{2}$/.test(m)).sort().reverse().map(id=>({id,nome:id===atual?`Fatura de ${nomeMes(id)} · mês atual`:`Fatura de ${nomeMes(id)}`}));
}

export function panoramaFaturas(dados,mes){
 const faturas=(dados.faturas??[]).filter(f=>(f.mes_referencia||String(f.vencimento).slice(0,7))===mes);
 const inventario=new Map();
 for(const c of dados.stg_contas??[]){
  if(c.tipo!=='CREDIT')continue;
  const anterior=inventario.get(c.id_conta);
  if(!anterior||c.data_posicao>anterior.data_posicao)inventario.set(c.id_conta,{...c,conta:c.nome,numero_cartao:c.numero});
 }
 for(const c of dados.cobertura_faturas??[])inventario.set(c.id_conta,{...inventario.get(c.id_conta),...c});
 for(const f of faturas)if(!inventario.has(f.id_conta))inventario.set(f.id_conta,f);
 const grupos=new Map();
 for(const c of inventario.values()){
  const nome=c.instituicao||'Instituição não informada';
  if(!grupos.has(nome))grupos.set(nome,{nome,cartoes:[],faturas:[]});
  grupos.get(nome).cartoes.push(c);
 }
 for(const f of faturas){const nome=f.instituicao||'Instituição não informada';if(!grupos.has(nome))grupos.set(nome,{nome,cartoes:[],faturas:[]});grupos.get(nome).faturas.push(f);}
 const bancos=[...grupos.values()].map(g=>{
  const faltantes=g.cartoes.filter(c=>!g.faturas.some(f=>f.id_conta===c.id_conta));
  return {...g,total:C.somar(g.faturas),faltantes,parcial:!!faltantes.length||g.faturas.some(f=>f.valor_brl==null)};
 }).sort((a,b)=>(b.total??-Infinity)-(a.total??-Infinity)||a.nome.localeCompare(b.nome));
 return {bancos,faturas,total:C.somar(faturas),parcial:bancos.some(b=>b.parcial),faltantes:bancos.flatMap(b=>b.faltantes)};
}

export function transacoesDasFaturas(faturas,transacoes){
 const ids=new Set(faturas.map(chave));
 return transacoes.filter(t=>t.id_fatura&&ids.has(chave(t)));
}

function nomeCartao(c){return `${c.conta||c.nome||'Cartão'}${c.numero_cartao?' · final '+String(c.numero_cartao).slice(-4):''}`;}
function observacaoBanco(g){
 if(!g.faturas.length){
  if(g.cartoes.some(c=>c.estado==='falha'))return 'Não foi possível atualizar';
  if(g.cartoes.every(c=>!c.estado||c.estado==='nao_coletado'))return 'Aguardando consulta às faturas';
  return 'Fatura não disponibilizada neste mês';
 }
 const datas=[...new Set(g.faturas.map(f=>C.dataBR(f.vencimento)))].join(', ');
 return `${g.faturas.length} ${g.faturas.length===1?'fatura':'faturas'} · vencimento ${datas}`;
}

export function telaFaturas(ctx){
 const {estado,dados,referencia,render}=ctx;
 estado.faturas??={mes:'andamento',selecao:'__total__'};
 const fs=estado.faturas,p=panoramaFaturas(dados,fs.mes);
 const abrir=selecao=>{fs.selecao=selecao;render();ctx.focarDetalhes?.();};
 const meses=[{id:'andamento',nome:'Em andamento · prévia parcial'},...mesesFaturas(dados.faturas??[],referencia)];
 const toolbar=`<div class="fatura-toolbar"><label class="chip"><span>Fatura</span><select id="fatura-mes" aria-label="Fatura ou mês de vencimento">${U.opcoes(meses,'id','nome',fs.mes)}</select></label><p class="fatura-periodo">${fs.mes==='andamento'?'Prévia em':'Faturas que vencem em'} <strong>${fs.mes==='andamento'?'andamento · valores provisórios':e(nomeMes(fs.mes))}</strong></p>${U.botao(ctx.sincronizando?'<span class="spinner"></span>Consultando instituições…':U.icone('atualizar')+(ctx.fonte==='offline'?'Atualizar exemplos':'Atualizar faturas'),ctx.sincronizar,'',ctx.sincronizando||!ctx.podeSincronizar?'disabled':'')}</div>`;
 const demonstracao=ctx.fonte==='offline'?U.aviso('Modo de demonstração: a atualização usa dados de exemplo. Para consultar seus bancos, inicie o servidor com --modo online.',true):'';
 if(fs.mes==='andamento')return toolbar+telaAndamento(ctx)+demonstracao+historicoFaturas(ctx);
 const aviso=p.parcial?`<p class="fatura-cobertura"><span class="ponto amber"></span> Total parcial${p.faltantes.length?' · '+p.faltantes.length+' cartão(ões) sem fatura neste mês':''}${p.faturas.some(f=>f.moeda&&f.moeda!=='BRL')?' · valores em outras moedas separados':''}${p.faturas.some(f=>f.valor_total==null)?' · total oficial não informado em alguma fatura':''}${p.faturas.some(f=>!f.moeda)?' · moeda não informada em alguma fatura':''}.</p>`:'';
 const lista=p.bancos.map(g=>{
  const estrangeiras=g.faturas.filter(f=>f.moeda!=='BRL').map(f=>dinheiro(f.valor_total,f.moeda));
  const valor=g.total===null?(estrangeiras.length?estrangeiras.join(' + '):'Não informada'):C.brl(g.total);
  return U.botao(`<span class="fatura-banco">${U.bancoNome(g.nome)}<small>${e(observacaoBanco(g))}</small>${g.faltantes.length&&g.faturas.length?`<small class="amber">${g.faltantes.length} cartão(ões) sem fatura</small>`:''}</span><span class="fatura-valor">${valor}${g.parcial&&g.total!==null?'<small>parcial em BRL</small>':''}${g.total!==null&&estrangeiras.length?`<small>${estrangeiras.join(' + ')}</small>`:''}</span>`,()=>abrir(g.nome),'fatura-linha'+(fs.selecao===g.nome?' selecionada':''),`aria-pressed="${fs.selecao===g.nome}" aria-controls="fatura-detalhes" aria-label="Faturas de ${e(g.nome)}: ${e(g.total===null?'valor não disponível em reais':C.brl(g.total))}. Abrir detalhes"`);
 }).join('');
 const total=U.botao(`<span>Total do mês<small>${p.faturas.length} ${p.faturas.length===1?'fatura informada':'faturas informadas'}${p.parcial?' · parcial em BRL':''}</small></span><span>${p.total===null?'Não informado':C.brl(p.total)}</span>`,()=>abrir('__total__'),'fatura-total'+(fs.selecao==='__total__'?' selecionada':''),`aria-pressed="${fs.selecao==='__total__'}" aria-controls="fatura-detalhes"`);
 return toolbar+aviso+`<div class="faturas-layout"><section class="faturas-lista" aria-label="Faturas por banco">${total}<div class="faturas-cabecalho"><span>Banco</span><span>Fatura</span></div>${lista||U.vazio('Nenhum cartão de crédito foi encontrado na publicação.')}<p class="sub">Valores das faturas informados pelas instituições, organizados pelo vencimento.</p></section>${detalhes(ctx,p)}</div>`+demonstracao+historicoFaturas(ctx);
}

// Totais oficiais por mês de vencimento: mostra a tendência e também escolhe o mês.
export function historicoFaturas(ctx){
 const fs=ctx.estado.faturas,faturas=ctx.dados.faturas??[];
 if(!faturas.length)return '';
 const meses=mesesFaturas(faturas,ctx.referencia).slice(0,12).reverse();
 const totais=meses.map(m=>({...m,total:C.somar(faturas.filter(f=>(f.mes_referencia||String(f.vencimento).slice(0,7))===m.id))}));
 const max=Math.max(...totais.map(t=>t.total??0),1);
 const colunas=totais.map(t=>U.botao(`<span class="value">${t.total===null?'—':Math.abs(t.total)>=1000?C.numero(Math.round(t.total/1000))+'k':C.numero(Math.round(t.total))}</span><span class="bar${t.total===null?' missing':''}" style="height:${t.total===null?0:Math.max(3,t.total/max*96)}px"></span><small>${e(C.mesBR(t.id).split(' de ')[0])}</small>`,()=>{fs.mes=t.id;fs.selecao='__total__';ctx.render();document.querySelector('#fatura-mes')?.focus();},'column'+(fs.mes===t.id?' selected':''),`aria-label="${e(t.nome)}: ${e(t.total===null?'não informada':C.brl(t.total))}. Abrir este mês"`)).join('');
 return U.painel('Histórico por vencimento','Totais oficiais informados pelas instituições, por mês de vencimento. Clique numa coluna para abrir o mês.',`<div class="columns historico-faturas">${colunas}</div>`,'<span class="badge">BRL · k = mil</span>');
}

function detalhes(ctx,p){
 const selecao=ctx.estado.faturas.selecao;
 if(!selecao)return `<section id="fatura-detalhes" class="fatura-detalhes fatura-espera" aria-labelledby="fatura-detalhes-titulo"><span class="fatura-ilustracao" aria-hidden="true">${U.icone('faturas')}</span><h2 id="fatura-detalhes-titulo" tabindex="-1">Detalhes da fatura</h2><p>Selecione um banco para ver os gastos dos cartões.<br>O Total do mês reúne todas as faturas.</p></section>`;
 const grupo=p.bancos.find(g=>g.nome===selecao);
 const faturas=selecao==='__total__'?p.faturas:grupo?.faturas??[];
 const faltantes=selecao==='__total__'?p.faltantes:grupo?.faltantes??[];
 const contas=selecao==='__total__'?p.bancos.flatMap(g=>g.cartoes):grupo?.cartoes??[];
 const tx=transacoesDasFaturas(faturas,ctx.dados.transacoes_analiticas??[]).sort((a,b)=>String(a.data).localeCompare(String(b.data))||String(a.descricao).localeCompare(String(b.descricao)));
 const total=C.somar(faturas);
 const tit=selecao==='__total__'?'Todos os bancos':selecao;
 const fechar=U.botao(U.icone('fechar'),()=>{ctx.estado.faturas.selecao=null;ctx.render();},'icon','aria-label="Fechar detalhes da fatura"');
 const cabecalho=`<div class="fatura-detalhes-topo"><div><h2 id="fatura-detalhes-titulo" tabindex="-1">${e(tit)}</h2><p class="sub">Detalhes da fatura · ${e(nomeMes(ctx.estado.faturas.mes))} · ${tx.length} ${tx.length===1?'lançamento vinculado':'lançamentos vinculados'}</p></div>${fechar}</div>`;
 const cartoes=faturas.map(f=>`<div class="fatura-cartao"><div><strong>${e(f.instituicao)} · ${e(nomeCartao(f))}</strong><small>Vencimento ${C.dataBR(f.vencimento)}${f.fechamento?' · fechamento '+C.dataBR(f.fechamento):''}</small></div><strong>${dinheiro(f.valor_total,f.moeda)}</strong></div>`).join('');
 const faltam=faltantes.length?U.aviso(`Fatura não informada neste mês: ${faltantes.map(c=>c.instituicao+' · '+nomeCartao(c)).join('; ')}. A ausência de informação não significa que não há valor a pagar.`):'';
 const erros=contas.filter(c=>c.estado==='falha');
 const falhas=erros.length?U.aviso('A última atualização falhou para '+erros.map(c=>nomeCartao(c)).join(', ')+'. Os dados anteriores permanecem visíveis; tente atualizar novamente.'):'';
 const tabela=tx.length?tabelaExtrato(ctx,tx,faturas):U.vazio(faturas.length?'A fonte ainda não forneceu lançamentos vinculados a esta fatura.':'A fonte ainda não disponibilizou esta fatura. Clique em Atualizar faturas para consultar.');
 const soma=C.somar(tx.map(t=>({...t,valor_conferencia:t.valor_brl==null?null:t.valor_assinado>0?-t.valor_brl:t.valor_brl})),'valor_conferencia');
 const comparavel=faturas.length>0&&tx.length>0&&faturas.every(f=>f.moeda==='BRL'&&f.valor_brl!=null)&&tx.every(t=>t.valor_brl!=null);
 const diferenca=comparavel&&Math.abs(total-soma)>0.01?U.aviso(`Total informado: ${C.brl(total)}. Lançamentos líquidos vinculados: ${C.brl(soma)}. Diferença: ${C.brl(total-soma)}. Confira saldos anteriores, encargos e vínculos ainda não fornecidos; a lista não comprova a composição completa.`):'';
 const cobertura=contas.filter(c=>c.transacoes_desde).map(c=>`${e(nomeCartao(c))}: lançamentos consultados desde ${C.dataBR(c.transacoes_desde)}${c.transacoes_em?' (consulta em '+C.dataBR(c.transacoes_em)+')':''}.`).join('<br>');
 const datas=contas.map(c=>c.coletado_em).filter(Boolean).sort();
 const meta=`<p class="sub fatura-rodape">${datas.length?'Última consulta disponível: '+C.dataBR(datas[0])+'. ':''}O total informado é o valor da fatura, sem cálculo de saldo restante após pagamentos. A data de compra pode pertencer a outro mês.</p>`;
 return `<section id="fatura-detalhes" class="fatura-detalhes" aria-labelledby="fatura-detalhes-titulo">${cabecalho}${cartoes}${faltam}${falhas}${diferenca}<div class="fatura-extrato">${tabela}</div>${cobertura?`<details class="fatura-cobertura-detalhe"><summary>Cobertura dos lançamentos</summary><p class="sub">${cobertura}</p></details>`:''}${meta}</section>`;
}
