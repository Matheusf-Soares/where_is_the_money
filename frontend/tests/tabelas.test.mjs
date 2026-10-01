import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../js/tabelas.mjs';
import * as U from '../js/ui.mjs';

test('ordenação compara dinheiro como número, datas cronologicamente e ausências por último',()=>{
 assert.deepEqual(T.ordenarLinhas([['R$ 90,00'],['R$ 1.200,00'],['Não disponível'],['-R$ 20,00']],[{n:'Valor'}],{coluna:0,direcao:'asc'}).map(r=>r[0]),['-R$ 20,00','R$ 90,00','R$ 1.200,00','Não disponível']);
 assert.deepEqual(T.ordenarLinhas([['02/01/2026'],['31/12/2025']],[{n:'Data',tipo:'data'}],{coluna:0,direcao:'asc'}).map(r=>r[0]),['31/12/2025','02/01/2026']);
});
test('chaves explícitas ignoram metadados e diferenciam valores arredondados na tela',()=>{
 const rows=[[{html:'1 mil<small>outro dado</small>',ordem:1040}],[{html:'1 mil',ordem:1010}],[{html:'—',ordem:null}]];
 assert.deepEqual(T.ordenarLinhas(rows,[{n:'Valor'}],{coluna:0,direcao:'desc'}).map(r=>r[0].ordem),[1040,1010,null]);
});
test('todas as colunas de dados são ordenáveis e as ações não são confundidas com dados',()=>{
 const html=U.tabela(['Descrição',{n:'Valor'},'Ações'],[['Loja','R$ 2,00','Editar']]);
 assert.equal((html.match(/class="sort-column"/g)||[]).length,2);
 assert.match(html,/aria-sort="none"/);
});
test('ordenação precede paginação e total permanece no rodapé separado',()=>{
 const rows=Array.from({length:70},(_,i)=>[String(i),{html:String(i),ordem:i}]);
 const html=U.tabela(['Descrição',{n:'Valor'}],rows,'',{ordemInicial:{coluna:1,direcao:'desc'},pagina:0,porPagina:50,rodape:['Total do recorte','2.415']});
 const body=html.match(/<tbody>([\s\S]*?)<\/tbody>/)[1];
 assert.equal((body.match(/<tr>/g)||[]).length,50);
 assert.match(body,/>69<\/td>/); assert.doesNotMatch(body,/>0<\/td>/);
 assert.match(html,/<tfoot>[\s\S]*table-total-gap[\s\S]*Total do recorte/);
 assert.doesNotMatch(body,/Total do recorte/);
});
test('datas e dia da semana são exibidos a partir dos campos já transformados',()=>{
 assert.match(U.dataGasto({data:'2026-09-18',dia_semana:'sexta-feira',data_gasto:'2026-09-12',dia_semana_gasto:'sábado'}),/12\/09\/2026/);
 assert.match(U.dataGasto({data:'2026-09-18',dia_semana:'sexta-feira',data_gasto:'2026-09-12',dia_semana_gasto:'sábado'}),/Lançamento: 18\/09\/2026/);
 assert.equal(U.diaGasto({data_gasto:'2026-09-12',dia_semana_gasto:'sábado'}),'sábado');
});
test('totais incluem todas as páginas e separam moedas sem conversão',()=>{
 const rows=Array.from({length:75},(_,i)=>({valor_brl:i+1,valor_original:i+1,moeda:'BRL'}));
 rows.push({valor_brl:null,valor_original:5,moeda:'USD'});
 const footer=U.totalBRL(rows,3,2);
 assert.match(footer[0][0],/BRL parcial/);
 assert.match(footer[0][2],/2.850,00/);
 assert.match(footer[1][2],/USD 5/);
 assert.match(U.totalBRL([{valor_brl:null,valor_original:5,moeda:'USD'}],2,1)[0][1],/Não disponível/);
});
