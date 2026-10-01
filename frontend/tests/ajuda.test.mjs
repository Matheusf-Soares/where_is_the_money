import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {telas,comum,avisos,caminho,outrosAngulos} from '../js/ajuda-conteudo.mjs';
// A ajuda localiza elementos pelo título e por seletor. Se a tela renomear um
// painel, a entrada perde o marcador sem erro nenhum: estes testes impedem isso.
const ler=nome=>readFileSync(new URL('../'+nome,import.meta.url),'utf8');
const app=ler('js/app.mjs'),rev=ler('js/revisao.mjs'),inv=ler('js/investimentos.mjs'),fonte=[ler('index.html'),app,rev,inv,ler('js/ui.mjs'),ler('js/faturas.mjs'),ler('js/tabelas.mjs'),ler('js/faturas-abertas.mjs'),ler('js/extrato-fatura.mjs')].join('\n');
const matriz=(texto,regex)=>JSON.parse(texto.match(regex)[1].replaceAll("'",'"'));
const telasApp=matriz(app,/const telas=(\[\[.*?\]\]);/).map(([id,,nome])=>({id,nome}));
const abasApp={explorar:matriz(app,/const tabs=U\.abas\((\[\[.*?\]\])/),revisao:matriz(rev,/tabs=(\[\[.*?\]\])/)};
const itensDe=(tela,aba)=>[...(telas[tela].itens??[]),...(telas[tela].abas?.[aba]?.itens??[])];
const todasCombinacoes=()=>Object.keys(telas).flatMap(t=>telas[t].abas?Object.keys(telas[t].abas).map(a=>[t,a]):[[t,'']]);
const todosItens=()=>[...comum,...Object.values(telas).flatMap(t=>[...(t.itens??[]),...Object.values(t.abas??{}).flatMap(a=>a.itens)])];

test('toda tela e toda aba da aplicação têm ajuda, e nenhuma ajuda sobra',()=>{
 assert.deepEqual(Object.keys(telas).sort(),telasApp.map(t=>t.id).sort());
 for(const [tela,abas] of Object.entries(abasApp)){
  assert.deepEqual(Object.keys(telas[tela].abas).sort(),abas.map(([id])=>id).sort(),tela);
  for(const [id,nome] of abas)assert.equal(telas[tela].abas[id].nome,nome,`${tela}/${id}`);
 }
});

test('títulos de painel e rótulos de métrica citados existem literalmente nas telas',()=>{
 for(const item of todosItens())for(const chave of ['painel','metrica'])for(const texto of [item.alvo?.[chave]].flat().filter(Boolean))
  assert.ok([app,rev,inv].some(f=>f.includes(`'${texto}'`)),`${item.id}: "${texto}" não aparece em app.mjs, revisao.mjs nem investimentos.mjs`);
});

test('ids e classes usados nos seletores existem no código das telas',()=>{
 for(const item of todosItens())for(const seletor of [item.alvo?.css].flat().filter(Boolean)){
  for(const [,id] of seletor.matchAll(/#([\w-]+)/g))assert.match(fonte,new RegExp(`id=\\\\?["']?${id}\\b`),`${item.id}: #${id}`);
  for(const [,classe] of seletor.matchAll(/\.([\w-]+)/g))assert.ok(fonte.includes(classe),`${item.id}: .${classe}`);
 }
});

test('todo destino de ligação é uma tela ou aba existente',()=>{
 const destinos=[...caminho.map(c=>c.ir),...outrosAngulos.map(t=>[t]),...Object.values(telas).flatMap(t=>[
  ...(t.ligacoes??[]).map(l=>l.ir),...(t.passos??[]).filter(p=>p.ir).map(p=>p.ir),
  ...[...(t.itens??[]),...Object.values(t.abas??{}).flatMap(a=>a.itens)].flatMap(i=>i.ir??[])]),...comum.flatMap(i=>i.ir??[])];
 for(const [tela,aba] of destinos){assert.ok(telas[tela],tela);if(aba)assert.ok(telas[tela].abas?.[aba],`${tela}/${aba}`);}
});

test('ids de entrada são únicos em cada tela, inclusive contra as entradas comuns',()=>{
 for(const [tela,aba] of todasCombinacoes()){
  const ids=[...comum,...itensDe(tela,aba)].map(i=>i.id);
  assert.equal(new Set(ids).size,ids.length,`${tela}/${aba}: ${ids}`);
 }
});

test('toda entrada tem texto e cada aviso explicado é um aviso que a aplicação escreve',()=>{
 for(const item of todosItens())assert.ok([item.texto].flat().join('').trim(),item.id);
 for(const aviso of avisos)assert.ok(app.includes(aviso.contem),aviso.contem);
});
