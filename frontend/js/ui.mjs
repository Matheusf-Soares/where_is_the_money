import {criarTabela,limparOrdemTabela} from './tabelas.mjs';
import {escapeHTML as e,brl,numero,dataBR,somar} from './core.mjs';
import {icone} from './icones.mjs';
export {icone};
let sequencia=0;const acoes=new Map();
export function limparAcoes(){acoes.clear();}
export function acao(fn){const id='a'+(++sequencia);acoes.set(id,fn);return id;}
export async function executarAcao(id,event){const fn=acoes.get(id);if(fn)await fn(event);}
export function botao(texto,fn,classe='',extra=''){return `<button type="button" class="${classe}" data-action="${acao(fn)}" ${extra}>${texto}</button>`;}
export function abas(itens,selecionada,selecionar,prefixo,rotulo,contagens={}){
 const contagem=id=>{const c=contagens[id];if(!c||!c.n)return '';return ` <span class="tab-contagem${c.alerta?' alerta':''}">${numero(c.n)}</span>`;};
 return `<div class="tabs" role="tablist" aria-label="${e(rotulo)}">${itens.map(([id,nome])=>botao(e(nome)+contagem(id),()=>{
  selecionar(id);
  document.getElementById(`${prefixo}-aba-${id}`)?.focus({preventScroll:true});
 },id===selecionada?'active':'',`id="${prefixo}-aba-${id}" role="tab" aria-selected="${id===selecionada}" aria-controls="${prefixo}-painel" tabindex="${id===selecionada?0:-1}"`)).join('')}</div>`;
}
export function tratarTeclasAbas(evento){
 const atual=evento.target.closest?.('[role="tab"]');
 if(!atual||!['ArrowLeft','ArrowRight','Home','End'].includes(evento.key))return;
 const abas=[...atual.parentElement.querySelectorAll('[role="tab"]')],indice=abas.indexOf(atual);
 const destino=evento.key==='Home'?0:evento.key==='End'?abas.length-1:(indice+(evento.key==='ArrowRight'?1:-1)+abas.length)%abas.length;
 evento.preventDefault();abas[destino].click();
}
export function tabela(cabecalhos,linhas,classe='',opcoes={}){return linhas.length?criarTabela(cabecalhos,linhas,classe,opcoes,botao):vazio();}
export {limparOrdemTabela};
export const celula=(html,ordem)=>({html,ordem});
export const valor=v=>celula(brl(v),v);
export function dataGasto(r){const d=r.data_gasto||r.data;return e(dataBR(d))+(r.data_gasto&&r.data_gasto!==r.data?`<small>Lançamento: ${e(dataBR(r.data))}</small>`:'');}
export const diaGasto=r=>r.dia_semana_gasto||r.dia_semana||'Não informado';
export function totalBRL(rows,colunas,colunaValor,{rotulo='Total do recorte',campo='valor_brl'}={}){
 const linha=(nome,valor)=>{const r=Array(colunas).fill('');r[0]=nome;r[colunaValor]=valor;return r;};
 const parcial=rows.some(r=>r[campo]==null);
 const totais=[linha(e(rotulo)+(parcial?' · BRL parcial':''),brl(somar(rows,campo)))];
 const moedas=[...new Set(rows.filter(r=>r[campo]==null&&r.moeda&&r.moeda!=='BRL').map(r=>r.moeda))].sort();
 for(const moeda of moedas)totais.push(linha(`Total ${e(moeda)} sem conversão`,`${e(moeda)} ${numero(somar(rows.filter(r=>r[campo]==null&&r.moeda===moeda),'valor_original'))}`));
 return totais;
}

export const vazio=(texto='Nenhum registro neste recorte. Ajuste o período ou os filtros.')=>`<div class="empty">${icone('info')}<span>${e(texto)}</span></div>`;
export const painel=(titulo,sub,conteudo,extra='',classe='')=>`<section class="panel${classe?' '+classe:''}"><div class="panel-head"><div><h2>${e(titulo)}</h2>${sub?`<p class="sub">${e(sub)}</p>`:''}</div>${extra?`<div class="panel-acoes">${extra}</div>`:''}</div>${conteudo}</section>`;
// Valor em reais com símbolo e centavos discretos, como nos extratos bem desenhados.
export const valorGrande=v=>e(v).replace(/^(-?)R\$[\s\u00a0]([\d.]+)(,\d{2})$/,(_,sinal,inteiro,centavos)=>`${sinal?'<span class="sinal">−</span>':''}<span class="moeda">R$</span>${inteiro}<span class="centavos">${centavos}</span>`);
export const metrica=(rotulo,valor,nota='',classe='',fn=null)=>`<article class="metric"><span class="label">${e(rotulo)}</span><strong class="${classe}">${fn?botao(valorGrande(valor),fn,'metric-link',`aria-label="${e(rotulo)}: ${e(valor)}. Ver lançamentos"`):valorGrande(valor)}</strong><small>${e(nota)}</small></article>`;
export const aviso=(texto,info=false,acao='')=>`<div class="notice${info?' info':''}">${icone(info?'info':'alerta')}<span class="notice-texto">${e(texto)}</span>${acao}</div>`;
export const opcoes=(rows,valor,rotulo,selecionado='')=>rows.map(r=>`<option value="${e(r[valor])}" ${String(r[valor])===String(selecionado)?'selected':''}>${e(r[rotulo])}</option>`).join('');
export const campo=(nome,rotulo,tipo='text',valor='',extra='')=>`<label class="field">${e(rotulo)}<input name="${nome}" type="${tipo}" value="${e(valor)}" ${extra}></label>`;
export const escolha=(nome,rotulo,opts,valor='')=>`<label class="field">${e(rotulo)}<select name="${nome}">${opcoes(opts.map(o=>typeof o==='string'?{id:o,nome:o}:o),'id','nome',valor)}</select></label>`;
export function barras(groups,click,maximo=8){const max=Math.max(...groups.map(g=>g.total??0),1);return groups.length?`<div class="bar-list">${groups.slice(0,maximo).map(g=>botao(`<span class="bar-label"><span>${e(g.nome)}</span><span class="num">${brl(g.total)}</span></span><span class="track"><i style="width:${Math.max(1,(g.total??0)/max*100)}%"></i></span>`,()=>click(g),'bar-row',`aria-label="${e(g.nome)}, ${e(brl(g.total))}, ver transações"`)).join('')}</div>`:vazio();}
export function abrirDialog(titulo,html){document.querySelector('#dialog-title').textContent=titulo;document.querySelector('#dialog-body').innerHTML=html;const d=document.querySelector('#detalhe');if(!d.open)d.showModal();}
export function toast(texto){const t=document.querySelector('#toast');t.textContent=texto;t.style.display='block';setTimeout(()=>t.style.display='none',7000);}
export function detalhesObjeto(row,labels){return `<dl class="detail-grid">${Object.entries(labels).map(([k,l])=>`<div><dt>${e(l)}</dt><dd>${e(row[k]===null||row[k]===undefined?'Não informado':typeof row[k]==='boolean'?(row[k]?'Sim':'Não'):row[k])}</dd></div>`).join('')}</dl>`;}
// Matiz estável por nome: o mesmo banco tem a mesma cor em todas as telas.
// Só azuis e violetas: verde e vermelho significam entrada e saída, não identidade.
export function matiz(nome){let h=0;for(const c of String(nome??''))h=(h*31+c.codePointAt(0))%997;return 190+h%110;}
const iniciais=n=>{const p=String(n??'?').replace(/[^\p{L}\p{N} ]/gu,' ').trim().split(/\s+/).filter(Boolean);return ((p[0]?.[0]??'?')+(p.length>1?p[1][0]:p[0]?.[1]??'')).toUpperCase();};
export const avatar=(n,classe='avatar')=>`<span class="${classe}" style="--h:${matiz(n)}" aria-hidden="true">${e(iniciais(n))}</span>`;
export const bancoNome=n=>`<span class="bank-name">${avatar(n,'bank-avatar')}<span>${e(n??'Não informado')}</span></span>`;
export const pilula=(texto,tipo='')=>`<span class="pill${tipo?' pill-'+tipo:''}">${texto}</span>`;
// Variação de gasto: subir é saída (coral), cair é alívio (verde). Para saldo e
// investimento é o contrário: `subirEBom` inverte as cores, não as setas.
export function delta(v,{subirEBom=false}={}){if(!v||v.delta===null||v.percentual===null)return `<span class="delta neutro">${e(v?.rotulo??'—')}</span>`;const sobe=v.delta>0,zero=Math.abs(v.delta)<.005;return `<span class="delta ${zero?'neutro':sobe!==subirEBom?'sobe':'desce'}">${zero?'':icone(sobe?'sobe':'desce')}${e(v.rotulo.replace(/^[+-]/,''))}</span>`;}
export const quota=(parte,total)=>{const p=total&&parte!==null?Math.max(0,parte/total*100):null;return `<span class="quota"><span class="track"><i style="width:${p===null?0:Math.max(1,p)}%"></i></span><span>${p===null?'—':numero(Math.round(p))+'%'}</span></span>`;};
export async function tratarClique(evento){const el=evento.target.closest('button[data-action]');if(!el||el.disabled)return;return executarAcao(el.dataset.action,evento);}
export async function tratarSubmit(evento){evento.preventDefault();if(evento.target.tagName==='FORM'&&evento.target.dataset.action)return executarAcao(evento.target.dataset.action,evento);}
// Série de valores por data, com área, rótulos de mínimo e máximo e pontos clicáveis.
export function graficoLinha(serie,abrir){
 const min=Math.min(...serie.map(s=>s.total)),max=Math.max(...serie.map(s=>s.total)),faixa=max-min||Math.abs(max)||1;
 const y=v=>12+(max-v)/faixa*70,points=serie.map((s,i)=>({...s,x:serie.length===1?50:2+i/(serie.length-1)*96,y:y(s.total)}));
 const linha=points.map(s=>s.x+','+s.y).join(' ');
 const area=`M${points[0].x},92 L${points.map(s=>s.x+','+s.y).join(' L')} L${points.at(-1).x},92 Z`;
 return `<div class="linechart"><div class="eixos"><span class="eixo" style="top:${y(max)}%">${e(brl(max))}</span><span class="eixo" style="top:${y(min)}%">${e(brl(min))}</span></div><div class="area"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line x1="0" x2="100" y1="${y(max)}" y2="${y(max)}" stroke="var(--linha-2)" stroke-dasharray="1 1.5" vector-effect="non-scaling-stroke"/><line x1="0" x2="100" y1="${y(min)}" y2="${y(min)}" stroke="var(--linha-2)" stroke-dasharray="1 1.5" vector-effect="non-scaling-stroke"/><path d="${area}" fill="rgba(110,159,255,.10)"/><polyline fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="${linha}"/></svg>`+points.map(s=>botao('<span class="sr-only">'+e(dataBR(s.data))+' · '+e(brl(s.total))+'</span>',()=>abrir(s.data),'point','style="left:'+s.x+'%;top:'+s.y+'%" title="'+e(dataBR(s.data))+' · '+e(brl(s.total))+'"')).join('')+'</div></div><div class="line-labels"><span>'+dataBR(serie[0].data)+'</span><span>'+dataBR(serie.at(-1).data)+'</span></div>';
}
