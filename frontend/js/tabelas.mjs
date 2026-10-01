// Ordenação e renderização compartilhadas pelas tabelas da aplicação.
import {escapeHTML as e} from './core.mjs';
const ordens=new Map();
const setas='<svg viewBox="0 0 12 12" aria-hidden="true"><path class="cima" d="M3.5 5 6 2.5 8.5 5"/><path class="baixo" d="M3.5 7 6 9.5 8.5 7"/></svg>';
const comparador=new Intl.Collator('pt-BR',{numeric:true,sensitivity:'base'});
const nome=c=>typeof c==='object'?c.n:c;
const numerico=c=>typeof c==='object'&&c.alinhar!=='esquerda';
const objeto=v=>v&&typeof v==='object'&&'html' in v;
const conteudo=v=>objeto(v)?v.html:v??'—';
const ordenavel=c=>typeof c==='object'&&c.ordenavel===false?false:!!nome(c)&&!['Ações','Revisar','Conferir'].includes(nome(c));

export function chaveCelula(valor,cabecalho){
 if(objeto(valor)&&'ordem' in valor)return valor.ordem;
 if(valor==null||typeof valor==='number')return valor;
 const texto=String(conteudo(valor)).replace(/<small\b[\s\S]*?<\/small>/gi,'').replace(/<[^>]*>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').trim();
 if(!texto||/^(—|não (disponível|informad[ao])|sem (dados|registros|posição)|novo|s\/ BRL)/i.test(texto))return null;
 const data=texto.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
 if(data)return `${data[3]}-${data[2]}-${data[1]}`;
 const numero=texto.replace(/R\$|BRL|%/g,'').replace(/\s/g,'').replace(/−/g,'-');
 if(/^[+-]?\d+(?:\.\d{3})*(?:,\d+)?$/.test(numero))return Number(numero.replace(/\./g,'').replace(',','.'));
 return texto;
}
export function comparar(a,b,direcao='asc'){
 if(a==null)return b==null?0:1;
 if(b==null)return -1;
 const v=typeof a==='number'&&typeof b==='number'?a-b:comparador.compare(String(a),String(b));
 return direcao==='desc'?-v:v;
}
export function ordenarLinhas(linhas,cabecalhos,ordem){
 if(!ordem)return [...linhas];
 return linhas.map((r,i)=>({r,i})).sort((a,b)=>comparar(chaveCelula(a.r[ordem.coluna],cabecalhos[ordem.coluna]),chaveCelula(b.r[ordem.coluna],cabecalhos[ordem.coluna]),ordem.direcao)||a.i-b.i).map(x=>x.r);
}
export function limparOrdemTabela(id){ordens.delete(id);}
function chaveDOM(td,cabecalho){
 if(td.hasAttribute('data-sort'))return JSON.parse(td.dataset.sort);
 const select=td.querySelector('select');
 if(select)return select.selectedOptions[0]?.textContent??null;
 const clone=td.cloneNode(true);clone.querySelectorAll('small,.sr-only').forEach(el=>el.remove());
 return chaveCelula(clone.textContent,cabecalho);
}
function ordenarDOM(evento,coluna,cabecalhos,opcoes){
 const table=evento.target.closest('table');if(!table)return;
 const atual=table.querySelectorAll('thead th')[coluna].getAttribute('aria-sort');
 const ordem={coluna,direcao:atual==='ascending'?'desc':'asc'};
 if(opcoes.id)ordens.set(opcoes.id,ordem);
 if(opcoes.aoOrdenar){opcoes.aoOrdenar(ordem);return;}
 const tbody=table.tBodies[0];
 [...tbody.rows].map((tr,i)=>({tr,i,chave:chaveDOM(tr.cells[coluna],cabecalhos[coluna])})).sort((a,b)=>comparar(a.chave,b.chave,ordem.direcao)||a.i-b.i).forEach(({tr})=>tbody.append(tr));
 table.querySelectorAll('thead th').forEach((th,i)=>{
  if(!th.hasAttribute('aria-sort'))return;
  th.setAttribute('aria-sort',i===coluna?(ordem.direcao==='asc'?'ascending':'descending'):'none');
 });
}
export function criarTabela(cabecalhos,linhas,classe,opcoes,botao){
 const ordem=(opcoes.id&&ordens.get(opcoes.id))||opcoes.ordemInicial;
 const sorted=ordenarLinhas(linhas,cabecalhos,ordem);
 const pagina=opcoes.porPagina?sorted.slice((opcoes.pagina||0)*opcoes.porPagina,((opcoes.pagina||0)+1)*opcoes.porPagina):sorted;
 const celulas=(row,inicio=0)=>row.map((v,i)=>`<td${numerico(cabecalhos[i+inicio])?' class="num"':''}${objeto(v)&&'ordem' in v?` data-sort="${e(JSON.stringify(v.ordem??null))}"`:''}>${conteudo(v)}</td>`).join('');
 const celulasRodape=row=>{const fim=row.findIndex((v,i)=>i>0&&v!=='');return fim>1?`<td colspan="${fim}">${conteudo(row[0])}</td>`+celulas(row.slice(fim),fim):celulas(row);};
 const rodapes=opcoes.rodape?(Array.isArray(opcoes.rodape[0])?opcoes.rodape:[opcoes.rodape]):[];
 return `<div class="table-wrap"><table class="${e(classe)}"><thead><tr>${cabecalhos.map((c,i)=>{
  const ativa=ordem?.coluna===i,dir=ativa?(ordem.direcao==='asc'?'ascending':'descending'):'none';
  return `<th${numerico(c)?' class="num"':''}${ordenavel(c)?` aria-sort="${dir}"`:''}>${ordenavel(c)?botao(`${e(nome(c))}<span class="sort-arrow" aria-hidden="true">${setas}</span>`,ev=>ordenarDOM(ev,i,cabecalhos,opcoes),'sort-column',`aria-label="Ordenar por ${e(nome(c))}"`):e(nome(c))}</th>`;
 }).join('')}</tr></thead><tbody>${pagina.map(r=>`<tr>${celulas(r)}</tr>`).join('')}</tbody>${rodapes.length?`<tfoot><tr class="table-total-gap" aria-hidden="true"><td colspan="${cabecalhos.length}"></td></tr>${rodapes.map(r=>`<tr class="table-total-row">${celulasRodape(r)}</tr>`).join('')}</tfoot>`:''}</table></div>`;
}
