import test from 'node:test';
import assert from 'node:assert/strict';
import * as F from '../js/faturas.mjs';
import {executarAcao,limparAcoes} from '../js/ui.mjs';

const cartoes=[
 {id_conta:'a1',instituicao:'Aurora',nome:'Principal',tipo:'CREDIT',numero:'1234',data_posicao:'2026-09-17'},
 {id_conta:'a2',instituicao:'Aurora',nome:'Adicional',tipo:'CREDIT',numero:'4567',data_posicao:'2026-09-17'},
 {id_conta:'b1',instituicao:'Boreal',nome:'Cartão',tipo:'CREDIT',data_posicao:'2026-09-17'},
 {id_conta:'c1',instituicao:'Cobalto',nome:'Cartão',tipo:'CREDIT',data_posicao:'2026-09-17'}
];
const fatura=(id,conta,banco,valor,mes='2026-09')=>({id_fatura:id,id_conta:conta,instituicao:banco,conta,mes_referencia:mes,vencimento:mes+'-20',moeda:'BRL',valor_total:valor,valor_brl:valor});
const ds={stg_contas:cartoes,cobertura_faturas:[],faturas:[fatura('f1','a1','Aurora',100),fatura('f2','a2','Aurora',200),fatura('f3','b1','Boreal',80),fatura('f0','a1','Aurora',999,'2026-08')],transacoes_analiticas:[]};

test('fatura atual segue calendário local mesmo com publicação de mês anterior',()=>{
 assert.equal(typeof F.dataAtualFaturas,'function');
 const referencia=F.dataAtualFaturas(new Date(2026,8,1,0,1));
 assert.equal(referencia,'2026-09-01');
 const meses=F.mesesFaturas([fatura('antiga','a1','Aurora',20,'2026-08')],referencia);
 assert.match(meses.find(m=>m.id==='2026-09').nome,/mês atual/);
 assert.doesNotMatch(meses.find(m=>m.id==='2026-08').nome,/atual/);
});

test('total oficial ausente não entra como zero na conferência nem como moeda estrangeira',()=>{
 const dados={...ds,faturas:[fatura('f1','a1','Aurora',null)],transacoes_analiticas:[{id_transacao:'t',id_conta:'a1',id_fatura:'f1',valor_brl:100,valor_assinado:-100,data:'2026-08-20'}]};
 const html=F.telaFaturas({estado:{faturas:{mes:'2026-09',selecao:'Aurora'}},dados,referencia:'2026-09-17',render:()=>{},sincronizar:()=>{},podeSincronizar:true});
 assert.doesNotMatch(html,/Diferença:|valores em outras moedas separados/);
 assert.match(html,/total oficial não informado/);
});

test('mês atual e histórico de faturas usam vencimento, inclusive meses sem dados',()=>{
 assert.equal(typeof F.mesesFaturas,'function');
 const meses=F.mesesFaturas(ds.faturas,'2026-09-17');
 assert.match(meses.find(m=>m.id==='2026-09').nome,/mês atual/);
 assert.match(meses.find(m=>m.id==='2026-08').nome,/agosto/i);
 assert.ok(meses.some(m=>m.id==='2026-07'));
});
test('banco soma seus cartões e Total soma somente faturas do mês escolhido',()=>{
 assert.equal(typeof F.panoramaFaturas,'function');
 const p=F.panoramaFaturas(ds,'2026-09');
 assert.equal(p.bancos.find(b=>b.nome==='Aurora').total,300);
 assert.equal(p.total,380);
 assert.equal(p.bancos.find(b=>b.nome==='Cobalto').total,null);
 assert.equal(p.parcial,true);
 assert.equal(F.panoramaFaturas(ds,'2026-08').total,999);
});
test('moeda estrangeira e cartão sem fatura mantêm total parcial sem somar USD como BRL',()=>{
 const estrangeira={...fatura('usd','c1','Cobalto',12),moeda:'USD',valor_brl:null};
 assert.equal(typeof F.panoramaFaturas,'function');
 const p=F.panoramaFaturas({...ds,faturas:[...ds.faturas,estrangeira]},'2026-09');
 assert.equal(p.total,380);
 assert.equal(p.parcial,true);
 assert.equal(p.bancos.find(b=>b.nome==='Cobalto').faturas[0].valor_total,12);
});
test('detalhes usam ID de fatura e cartão, preservando compras de outro mês e créditos',()=>{
 assert.equal(typeof F.transacoesDasFaturas,'function');
 const tx=[
  {id_transacao:'compra',id_fatura:'f1',id_conta:'a1',data:'2026-07-01',valor_assinado:-100},
  {id_transacao:'estorno',id_fatura:'f1',id_conta:'a1',data:'2026-09-02',valor_assinado:20},
  {id_transacao:'outro-cartao',id_fatura:'f1',id_conta:'b1',data:'2026-09-01'},
  {id_transacao:'sem-vinculo',id_conta:'a1',data:'2026-09-01'}
 ];
 assert.deepEqual(F.transacoesDasFaturas([ds.faturas[0]],tx).map(t=>t.id_transacao),['compra','estorno']);
});
test('clique na linha do banco e no Total abre o mesmo painel com escopos próprios',async()=>{
 assert.equal(typeof F.telaFaturas,'function');
 const estado={faturas:{mes:'2026-09',selecao:null}};
 let renders=0;
 const ctx={estado,dados:ds,referencia:'2026-09-17',render:()=>renders++,detalhe:()=>{},sincronizar:()=>{},podeSincronizar:true};
 limparAcoes();
 const html=F.telaFaturas(ctx);
 const actions=[...html.matchAll(/<button\b([^>]*)data-action="([^"]+)"([^>]*)>([\s\S]*?)<\/button>/g)];
 const banco=actions.find(a=>a[4].includes('Aurora'));
 const total=actions.find(a=>a[4].includes('Total do mês'));
 assert.ok(banco);assert.ok(total);
 await executarAcao(banco[2],{});
 assert.equal(estado.faturas.selecao,'Aurora');
 assert.match(F.telaFaturas(ctx),/Detalhes da fatura/);
 await executarAcao(total[2],{});
 assert.equal(estado.faturas.selecao,'__total__');
 assert.equal(renders,2);
});
