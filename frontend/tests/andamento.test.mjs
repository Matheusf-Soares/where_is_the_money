import test from 'node:test';
import assert from 'node:assert/strict';
import * as F from '../js/faturas.mjs';
import * as A from '../js/faturas-abertas.mjs';
import {tabelaExtrato} from '../js/extrato-fatura.mjs';

test('andamento é a opção inicial e mês corrente não se chama fatura atual',()=>{
 const estado={};
 const html=F.telaFaturas({estado,dados:{},referencia:'2026-09-18',render:()=>{},sincronizar:()=>{}});
 assert.equal(estado.faturas.mes,'andamento');
 assert.match(html,/Em andamento/);
 assert.doesNotMatch(F.mesesFaturas([],'2026-09-18').find(m=>m.id==='2026-09').nome,/Fatura atual/);
});
test('prévia soma apenas líquidos disponíveis por conta e preserva ausência',()=>{
 const p=A.panoramaAndamento({faturas_abertas:[{id_conta:'a',instituicao:'Aurora',liquido_conhecido_brl:120},{id_conta:'b',instituicao:'Aurora',liquido_conhecido_brl:30},{id_conta:'c',instituicao:'Boreal',liquido_conhecido_brl:null}]});
 assert.equal(p.total,150);assert.equal(p.bancos.find(b=>b.nome==='Boreal').total,null);
 assert.equal(p.bancos.find(b=>b.nome==='Aurora').total,150);
});
test('publicação antiga sem view aberta ainda mostra os cartões conhecidos',()=>{
 const p=A.panoramaAndamento({faturas_abertas:[],cobertura_faturas:[{id_conta:'cc',instituicao:'Aurora'}]});
 assert.equal(p.bancos.length,1);assert.equal(p.total,null);
});
test('extrato tem data e dia, total líquido com créditos e moeda original separada',()=>{
 const tx=[{descricao:'Compra',data:'2026-09-18',dia_semana:'sexta-feira',valor_brl:100,valor_original:100,moeda:'BRL',valor_assinado:-100},{descricao:'Estorno',data:'2026-09-18',dia_semana:'sexta-feira',valor_brl:20,valor_original:20,moeda:'BRL',valor_assinado:20},{descricao:'Exterior',data:'2026-09-18',valor_brl:null,valor_original:5,moeda:'USD',valor_assinado:-5}];
 const html=tabelaExtrato({detalhe:()=>{}},tx,[]);
 assert.match(html,/sexta-feira/);assert.match(html,/18\/09\/2026/);
 assert.match(html,/<tfoot>[\s\S]*80,00[\s\S]*USD 5/);
 assert.match(html,/BRL parcial/);
});
