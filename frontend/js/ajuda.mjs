// Ajuda contextual: painel lateral que explica a tela atual e marca na própria
// página, com números, cada elemento explicado. O conteúdo vive em ajuda-conteudo.mjs.
import {escapeHTML as e} from './core.mjs';
import {telas as conteudo,comum,avisos,caminho,outrosAngulos} from './ajuda-conteudo.mjs';

// Acima desta largura o painel empurra o conteúdo em vez de cobri-lo; abaixo, o
// que sobraria para a página seria estreito demais e ele passa a sobrepor.
// Mantenha igual à media query do modo empurrar em styles.css.
const EMPURRA='(min-width: 1440px)';
let ctx=null,aberta=false,marcar=true,chave='',abertos=new Set(),resolvidos=[],quadro=0,destacado=null;
let fab,painel,titulo,corpo,camada;

const lista=v=>v===undefined?[]:Array.isArray(v)?v:[v];
const visivel=el=>!!el&&el.getClientRects().length>0;
const suave=()=>matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
function lerPreferencia(nome,padrao){try{const v=localStorage.getItem('ajuda.'+nome);return v===null?padrao:v==='1';}catch{return padrao;}}
function gravarPreferencia(nome,valor){try{localStorage.setItem('ajuda.'+nome,valor?'1':'0');}catch{}}

function abaAtual(){const {tela,aba,revisao}=ctx.estado;return tela==='explorar'?aba:tela==='revisao'?revisao:'';}
function paginaAtual(){const base=conteudo[ctx.estado.tela]??{},sub=abaAtual(),aba=base.abas?.[sub];return {...base,sub,aba,pergunta:aba?.pergunta??base.pergunta,itens:[...(base.itens??[]),...(aba?.itens??[])]};}
function nomeDestino([tela,sub]){const nome=ctx.telas.find(t=>t[0]===tela)?.[2]??tela,aba=sub&&conteudo[tela]?.abas?.[sub]?.nome;return aba?`${nome} › ${aba}`:nome;}

function localizar(alvo){
 if(!alvo)return null;
 for(const seletor of lista(alvo.css)){const el=document.querySelector(seletor);if(visivel(el))return el;}
 const porTexto=(seletor,textos,bloco)=>[...document.querySelectorAll(seletor)].find(n=>lista(textos).includes(n.textContent.trim())&&visivel(n))?.closest(bloco)??null;
 if(alvo.painel)return porTexto('#conteudo .panel-head h2',alvo.painel,'.panel');
 if(alvo.metrica)return porTexto('#conteudo .metric .label',alvo.metrica,'.metric');
 return null;
}
// Presentes primeiro, numerados na ordem em que aparecem na página; depois os ausentes.
function resolver(itens,rotular){
 const todos=itens.map(item=>({item,el:localizar(item.alvo)}));
 const presentes=todos.filter(r=>r.el).sort((a,b)=>a.el===b.el?0:a.el.compareDocumentPosition(b.el)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1);
 presentes.forEach((r,i)=>r.rotulo=rotular(i));
 return [...presentes,...todos.filter(r=>!r.el)];
}
function avisosNaTela(){const texto=document.querySelector('#notices')?.textContent??'';const achados=avisos.filter(a=>texto.includes(a.contem));return achados.length?achados.map(a=>[a.termo,a.texto]):null;}

const botaoIr=(ir,texto)=>`<button type="button" class="ajuda-ir" data-ajuda-ir="${e(ir.join(':'))}">${e(texto)}</button>`;
const paragrafos=t=>lista(t).map(p=>`<p>${e(p)}</p>`).join('');
const termos=ts=>ts?.length?`<dl class="ajuda-termos">${ts.map(([t,d])=>`<div><dt>${e(t)}</dt><dd>${e(d)}</dd></div>`).join('')}</dl>`:'';
function entrada({item,el,rotulo},nota=''){
 const acoes=(el?`<button type="button" class="ajuda-mostrar" data-ajuda-mostrar="${e(item.id)}">Mostrar na tela</button>`:'')+lista(item.ir).map(ir=>botaoIr(ir,'Abrir '+nomeDestino(ir))).join('');
 return `<li data-ajuda-item="${e(item.id)}"><details${abertos.has(item.id)?' open':''}><summary><span class="ajuda-marca${rotulo?'':' vazia'}" aria-hidden="true">${rotulo??''}</span><span class="ajuda-nome">${e(item.titulo)}${!el&&item.quando?`<small>${e(item.quando)}</small>`:''}</span></summary><div class="ajuda-texto">${paragrafos(item.texto)}${nota?`<p>${e(nota)}</p>`:''}${termos(item.id==='avisos'?avisosNaTela()??item.termos:item.termos)}${acoes?`<div class="ajuda-acoes">${acoes}</div>`:''}</div></details></li>`;
}
function passo(p){return typeof p==='string'?`<li>${e(p)}</li>`:`<li>${e(p.texto)} ${botaoIr(p.ir,'Abrir '+nomeDestino(p.ir))}</li>`;}
function trilha(){
 const {tela}=ctx.estado,sub=abaAtual();
 const aqui=caminho.findIndex(c=>c.ir[0]===tela&&(tela!=='revisao'||(c.ir[1]==='auditoria')===(sub==='auditoria')));
 return `<ol class="ajuda-caminho">${caminho.map((c,i)=>`<li${i===aqui?' class="aqui"':''}>${botaoIr(c.ir,nomeDestino(c.ir))}${i===aqui?'<span class="ajuda-aqui">você está aqui</span>':''}<p>${e(c.texto)}</p></li>`).join('')}</ol><p class="ajuda-angulos">Outros ângulos sobre os mesmos dados: ${outrosAngulos.map(t=>botaoIr([t],nomeDestino([t]))).join(', ')}.</p>`;
}

function desenhar(){
 const p=paginaAtual(),novaChave=ctx.estado.tela+':'+p.sub,mesmaTela=novaChave===chave;
 const rolagem=mesmaTela?painel.scrollTop:0,focoDentro=painel.contains(document.activeElement)&&document.activeElement!==titulo;
 if(!mesmaTela){abertos=new Set();chave=novaChave;}
 const itens=resolver(p.itens,i=>String(i+1)),gerais=resolver(comum,i=>String.fromCharCode(65+i));
 resolvidos=[...itens,...gerais].filter(r=>r.el);
 titulo.textContent=nomeDestino([ctx.estado.tela]);
 painel.querySelector('.ajuda-aba').textContent=p.aba?'Aba '+p.aba.nome:'';
 painel.querySelector('.ajuda-pergunta').textContent=p.pergunta??'';
 painel.querySelector('.ajuda-nota').innerHTML=p.filtros?`<strong>Filtros nesta tela</strong>${e(p.filtros)}`:'';
 corpo.innerHTML=
  `<section><h3>Como usar</h3><ol class="ajuda-passos">${(p.passos??[]).map(passo).join('')}</ol></section>`+
  `<section><div class="ajuda-secao"><h3>O que cada parte mostra</h3><label class="ajuda-chave"><input type="checkbox" data-ajuda-marcar ${marcar?'checked':''}>Números na tela</label></div><ol class="ajuda-itens">${itens.map(r=>entrada(r)).join('')}</ol></section>`+
  `<section><h3>Ligações com outras telas</h3><ul class="ajuda-ligacoes">${(p.ligacoes??[]).map(l=>`<li>${botaoIr(l.ir,nomeDestino(l.ir))}<p>${e(l.texto)}</p></li>`).join('')}</ul></section>`+
  `<section><h3>Comum a todas as telas</h3><ol class="ajuda-itens">${gerais.map(r=>entrada(r,r.item.id==='filtros'&&p.filtros?'Nesta tela: '+p.filtros:'')).join('')}</ol></section>`+
  `<section><h3>O caminho de uma investigação</h3>${trilha()}</section>`+
  `<p class="ajuda-atalhos"><kbd>?</kbd> abre e fecha esta ajuda. <kbd>Esc</kbd> fecha.</p>`;
 painel.scrollTop=rolagem;
 if(focoDentro)titulo.focus({preventScroll:true});
 destacar(null);
 posicionar();
}

// Marcadores ficam numa camada própria sobre o documento: nada é inserido nos
// elementos da tela, então rótulos, tabelas e overflow continuam intactos.
// Cada marcador é reaproveitado entre ajustes de layout: trocar o elemento sob o
// cursor dispararia pointerout e apagaria o destaque que o usuário está vendo.
function posicionar(){
 cancelAnimationFrame(quadro);
 quadro=requestAnimationFrame(()=>{
  const antigos=new Map([...camada.children].map(p=>[p.dataset.ajudaPino,p])),atuais=new Set();
  if(aberta&&marcar)for(const r of resolvidos){
   if(!r.el.isConnected||!visivel(r.el))continue;
   const caixa=r.el.getBoundingClientRect(),pino=antigos.get(r.item.id)??camada.appendChild(document.createElement('span'));
   // Cartões e painéis têm respiro interno e o marcador fica no canto. Em
   // elementos cujo texto encosta na borda, ele sobe para não cobrir a primeira letra.
   const estilo=getComputedStyle(r.el),colado=parseFloat(estilo.paddingLeft)<8&&parseFloat(estilo.paddingTop)<8;
   pino.className='ajuda-pino'+(r.item.id===destacado?' ativo':'');pino.dataset.ajudaPino=r.item.id;pino.textContent=r.rotulo;
   pino.style.left=caixa.left+scrollX+(colado?12:0)+'px';pino.style.top=caixa.top+scrollY-(colado?12:0)+'px';
   atuais.add(r.item.id);
  }
  for(const [id,pino] of antigos)if(!atuais.has(id))pino.remove();
 });
}
function destacar(id){
 destacado=id;
 document.querySelectorAll('.ajuda-destaque').forEach(el=>el.classList.remove('ajuda-destaque'));
 corpo.querySelectorAll('li.ativo').forEach(li=>li.classList.remove('ativo'));
 camada.querySelectorAll('.ajuda-pino').forEach(p=>p.classList.toggle('ativo',p.dataset.ajudaPino===id));
 const r=resolvidos.find(r=>r.item.id===id);
 if(!r)return;
 r.el.classList.add('ajuda-destaque');
 corpo.querySelector(`li[data-ajuda-item="${CSS.escape(id)}"]`)?.classList.add('ativo');
}
function mostrar(id){
 const r=resolvidos.find(r=>r.item.id===id);
 if(!r)return;
 // Painel sobreposto esconderia o elemento: fecha e deixa a tela à vista.
 if(!matchMedia(EMPURRA).matches)fechar();
 r.el.scrollIntoView({behavior:suave(),block:'center'});
 r.el.classList.remove('ajuda-lampejo');void r.el.offsetWidth;r.el.classList.add('ajuda-lampejo');
 setTimeout(()=>r.el.classList.remove('ajuda-lampejo'),1800);
}
function abrirEntrada(id){
 const li=corpo.querySelector(`li[data-ajuda-item="${CSS.escape(id)}"]`);
 if(!li)return;
 li.querySelector('details').open=true;abertos.add(id);
 li.scrollIntoView({behavior:suave(),block:'nearest'});
 li.querySelector('summary').focus({preventScroll:true});
 destacar(id);
}

function sincronizarModalidade(){
 const sobreposta=aberta&&!matchMedia(EMPURRA).matches;
 document.querySelector('.shell').inert=sobreposta;
 if(sobreposta){painel.setAttribute('role','dialog');painel.setAttribute('aria-modal','true');}
 else{painel.removeAttribute('role');painel.removeAttribute('aria-modal');}
}
function manterFoco(event){
 if(event.key!=='Tab'||!aberta||matchMedia(EMPURRA).matches)return;
 const focaveis=[...painel.querySelectorAll('button,input,select,textarea,summary,a[href]')]
  .filter(el=>!el.disabled&&el.getClientRects().length);
 if(!focaveis.length)return;
 const primeiro=focaveis[0],ultimo=focaveis.at(-1);
 if(event.shiftKey&&document.activeElement===primeiro){event.preventDefault();ultimo.focus();}
 else if(!event.shiftKey&&document.activeElement===ultimo){event.preventDefault();primeiro.focus();}
}

function abrir(focar=true){
 aberta=true;gravarPreferencia('aberta',true);
 document.body.classList.add('ajuda-aberta');painel.classList.add('aberta');painel.inert=false;
 fab.setAttribute('aria-expanded','true');
 desenhar();
 sincronizarModalidade();
 if(focar||!matchMedia(EMPURRA).matches)titulo.focus({preventScroll:true});
}
function fechar(){
 const focoDentro=painel.contains(document.activeElement);
 aberta=false;gravarPreferencia('aberta',false);
 document.body.classList.remove('ajuda-aberta');painel.classList.remove('aberta');painel.inert=true;
 fab.setAttribute('aria-expanded','false');
 sincronizarModalidade();
 destacar(null);camada.replaceChildren();
 if(focoDentro)fab.focus({preventScroll:true});
}
const alternar=()=>aberta?fechar():abrir();

// Chamada ao fim de cada render(): a tela mudou, a ajuda acompanha.
export function atualizarAjuda(){if(ctx&&aberta)desenhar();}

export function montarAjuda(contexto){
 ctx=contexto;
 fab=document.querySelector('#ajuda-botao');painel=document.querySelector('#ajuda');
 titulo=painel.querySelector('#ajuda-titulo');corpo=painel.querySelector('.ajuda-corpo');camada=document.querySelector('.ajuda-camada');
 marcar=lerPreferencia('marcadores',true);
 fab.addEventListener('click',alternar);
 painel.addEventListener('click',event=>{
  const alvo=event.target.closest('[data-ajuda-fechar],[data-ajuda-ir],[data-ajuda-mostrar]');
  if(!alvo)return;
  if(alvo.dataset.ajudaIr!==undefined){const [tela,sub]=alvo.dataset.ajudaIr.split(':');ctx.irPara(tela,sub);titulo.focus({preventScroll:true});}
  else if(alvo.dataset.ajudaMostrar!==undefined)mostrar(alvo.dataset.ajudaMostrar);
  else fechar();
 });
 painel.addEventListener('change',event=>{if(event.target.dataset.ajudaMarcar!==undefined){marcar=event.target.checked;gravarPreferencia('marcadores',marcar);posicionar();}});
 // toggle não borbulha; a captura acompanha quais entradas estão abertas.
 painel.addEventListener('toggle',event=>{const id=event.target.closest?.('li[data-ajuda-item]')?.dataset.ajudaItem;if(id)event.target.open?abertos.add(id):abertos.delete(id);},true);
 const sobreEntrada=event=>destacar(event.target.closest?.('li[data-ajuda-item]')?.dataset.ajudaItem??null);
 corpo.addEventListener('pointerover',sobreEntrada);corpo.addEventListener('focusin',sobreEntrada);
 corpo.addEventListener('pointerleave',()=>destacar(null));
 corpo.addEventListener('focusout',event=>{if(!corpo.contains(event.relatedTarget))destacar(null);});
 camada.addEventListener('click',event=>{const id=event.target.dataset?.ajudaPino;if(id)abrirEntrada(id);});
 camada.addEventListener('pointerover',event=>{const id=event.target.dataset?.ajudaPino;if(id)destacar(id);});
 camada.addEventListener('pointerout',event=>{if(!event.relatedTarget?.dataset?.ajudaPino)destacar(null);});
 document.addEventListener('keydown',event=>{
  const el=event.target,editando=el.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
  manterFoco(event);
  if(event.key==='?'&&!editando&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!document.querySelector('dialog[open]')){event.preventDefault();alternar();}
  // Com um dialog aberto, Esc pertence a ele.
  else if(event.key==='Escape'&&aberta&&!document.querySelector('dialog[open]'))fechar();
 });
 // O painel inteiro rola; a faixa do topo ganha uma linha quando há conteúdo sob ela.
 painel.addEventListener('scroll',()=>painel.classList.toggle('rolado',painel.scrollTop>4),{passive:true});
 addEventListener('resize',()=>{sincronizarModalidade();posicionar();});
 const observador=new ResizeObserver(posicionar);
 observador.observe(document.body);observador.observe(document.querySelector('.workspace'));
 if(lerPreferencia('aberta',false)){
  // Reabre sem animar: quem recarrega a página não precisa ver o painel deslizar de novo.
  document.documentElement.classList.add('ajuda-sem-transicao');
  abrir(false);
  requestAnimationFrame(()=>requestAnimationFrame(()=>document.documentElement.classList.remove('ajuda-sem-transicao')));
 }
}
