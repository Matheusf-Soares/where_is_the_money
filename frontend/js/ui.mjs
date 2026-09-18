import {escapeHTML as e,brl,numero,dataBR} from './core.mjs';
let sequencia=0;const acoes=new Map();
export function limparAcoes(){acoes.clear();}
export function acao(fn){const id='a'+(++sequencia);acoes.set(id,fn);return id;}
export async function executarAcao(id,event){const fn=acoes.get(id);if(fn)await fn(event);}
export function botao(texto,fn,classe='',extra=''){return `<button type="button" class="${classe}" data-action="${acao(fn)}" ${extra}>${texto}</button>`;}
export function tabela(cabecalhos,linhas,classe=''){return linhas.length?`<div class="table-wrap"><table class="${classe}"><thead><tr>${cabecalhos.map(c=>`<th${typeof c==='object'?' class="num"':''}>${e(typeof c==='object'?c.n:c)}</th>`).join('')}</tr></thead><tbody>${linhas.map(c=>`<tr>${c.map((v,i)=>`<td${typeof cabecalhos[i]==='object'?' class="num"':''}>${v??'—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:vazio();}
export const vazio=(texto='Nenhum registro neste recorte. Ajuste o período ou os filtros.')=>`<div class="empty">${e(texto)}</div>`;
export const painel=(titulo,sub,conteudo,extra='')=>`<section class="panel"><div class="panel-head"><div><h2>${e(titulo)}</h2><p class="sub">${e(sub)}</p></div>${extra}</div>${conteudo}</section>`;
export const metrica=(rotulo,valor,nota='',classe='',fn=null)=>`<article class="metric"><span class="label">${e(rotulo)}</span><strong class="${classe}">${fn?botao(e(valor),fn,'metric-link',`aria-label="${e(rotulo)}: ${e(valor)}. Ver lançamentos"`):e(valor)}</strong><small>${e(nota)}</small></article>`;
export const aviso=(texto,info=false)=>`<div class="notice${info?' info':''}">${e(texto)}</div>`;
export const opcoes=(rows,valor,rotulo,selecionado='')=>rows.map(r=>`<option value="${e(r[valor])}" ${String(r[valor])===String(selecionado)?'selected':''}>${e(r[rotulo])}</option>`).join('');
export const campo=(nome,rotulo,tipo='text',valor='',extra='')=>`<label class="field">${e(rotulo)}<input name="${nome}" type="${tipo}" value="${e(valor)}" ${extra}></label>`;
export const escolha=(nome,rotulo,opts,valor='')=>`<label class="field">${e(rotulo)}<select name="${nome}">${opcoes(opts.map(o=>typeof o==='string'?{id:o,nome:o}:o),'id','nome',valor)}</select></label>`;
export function barras(groups,click,maximo=8){const max=Math.max(...groups.map(g=>g.total??0),1);return groups.length?`<div class="bar-list">${groups.slice(0,maximo).map(g=>botao(`<span class="bar-label"><span>${e(g.nome)}</span><span class="num">${brl(g.total)}</span></span><span class="track"><i style="width:${Math.max(1,(g.total??0)/max*100)}%"></i></span>`,()=>click(g),'bar-row',`aria-label="${e(g.nome)}, ${e(brl(g.total))}, ver transações"`)).join('')}</div>`:vazio();}
export function abrirDialog(titulo,html){document.querySelector('#dialog-title').textContent=titulo;document.querySelector('#dialog-body').innerHTML=html;const d=document.querySelector('#detalhe');if(!d.open)d.showModal();}
export function toast(texto){const t=document.querySelector('#toast');t.textContent=texto;t.style.display='block';setTimeout(()=>t.style.display='none',7000);}
export function detalhesObjeto(row,labels){return `<dl class="detail-grid">${Object.entries(labels).map(([k,l])=>`<div><dt>${e(l)}</dt><dd>${e(row[k]===null||row[k]===undefined?'Não informado':typeof row[k]==='boolean'?(row[k]?'Sim':'Não'):row[k])}</dd></div>`).join('')}</dl>`;}
export const bancoNome=n=>`<span class="bank-name"><span class="bank-avatar">${e(String(n??'?').slice(0,2).toUpperCase())}</span>${e(n??'Não informado')}</span>`;
export async function tratarClique(evento){const el=evento.target.closest('button[data-action]');if(!el||el.disabled)return;return executarAcao(el.dataset.action,evento);}
export async function tratarSubmit(evento){evento.preventDefault();if(evento.target.tagName==='FORM'&&evento.target.dataset.action)return executarAcao(evento.target.dataset.action,evento);}
