import test from 'node:test';
import assert from 'node:assert/strict';
import {selecionarMesResumo,mesesDoSeletor} from '../js/resumo-mes.mjs';

function estado(){return {tela:'resumo',filtros:{inicio:'2026-08-01',fim:'2026-08-31',banco:'Banco A',conta:'conta-1',modo:'compra'},drill:{titulo:'Anterior'},pagina:3,selecionadas:new Set(['transacao-1'])};}

test('selecionar barra de mês anterior filtra o Resumo inteiro e preserva os demais filtros',()=>{
 const atual=estado();
 selecionarMesResumo(atual,'2026-05','2026-08-23');
 assert.equal(atual.tela,'resumo');
 assert.deepEqual(atual.filtros,{inicio:'2026-05-01',fim:'2026-05-31',banco:'Banco A',conta:'conta-1',modo:'compra'});
 assert.equal(atual.drill,null);
 assert.equal(atual.pagina,0);
 assert.equal(atual.selecionadas.size,0);
});

test('selecionar o mês em curso limita o período à data de referência',()=>{
 const atual=estado();
 selecionarMesResumo(atual,'2026-08','2026-08-23');
 assert.equal(atual.filtros.inicio,'2026-08-01');
 assert.equal(atual.filtros.fim,'2026-08-23');
});

test('seletor mantém visível um mês escolhido antes da janela inicial de 12 meses',()=>{
 const meses=mesesDoSeletor('2026-08-23','2025-03-01');
 assert.equal(meses[0],'2026-08');
 assert.ok(meses.includes('2025-03'));
 assert.equal(meses.length,13);
});
