import * as C from './core.mjs';
import * as U from './ui.mjs';
const e=C.escapeHTML;
export const nomeCartao=c=>`${c.conta||c.nome||'Cartão'}${c.numero_cartao?' · final '+String(c.numero_cartao).slice(-4):''}`;
export function tabelaExtrato(ctx,tx,cartoes,{rotuloTotal='Total líquido dos lançamentos',somentePagamentos=false}={}){
 const valores=tx.map(t=>{const sinal=!somentePagamentos&&t.valor_assinado>0?-1:1;return {...t,valor_brl:t.valor_brl==null?null:sinal*t.valor_brl,valor_original:t.valor_original==null?null:sinal*t.valor_original};});
 const linhas=tx.map((t,i)=>{
  const v=valores[i],cartao=cartoes.find(c=>c.id_conta===t.id_conta)??t;
  const valor=v.valor_brl==null?`${e(t.moeda)} ${C.numero(v.valor_original)}`:C.brl(v.valor_brl);
  const tipo=t.tipo_lancamento==='pagamento'?'pagamento de fatura':t.valor_assinado>0?'crédito / estorno':'';
  return [U.celula(`<div class="fatura-compra">${U.botao(e(t.estabelecimento||t.descricao||'Lançamento'),()=>ctx.detalhe(t),'link')}<small>${e(t.instituicao)} · ${e(nomeCartao(cartao))}${t.e_parcelado?' · parcela '+e(t.parcela_numero??'?')+'/'+e(t.parcela_total??'?'):''}${tipo?' · '+tipo:''}${t.classificacao_periodo&&t.classificacao_periodo!=='andamento'?' · '+e(C.rotulo(t.classificacao_periodo)):''}</small></div>`,t.estabelecimento||t.descricao),
   U.celula(`${U.dataGasto(t)}<small>${e(U.diaGasto(t))}</small>`,t.data_gasto||t.data),
   U.celula(`<span class="valor-cell${v.valor_brl<0?' pos':''}">${valor}</span>${t.moeda!=='BRL'&&v.valor_brl!=null?`<small>${e(t.moeda)} ${C.numero(v.valor_original)}</small>`:''}`,v.valor_brl)];
 });
 return U.tabela(['Compra / lançamento','Data do gasto',{n:'Valor BRL'}],linhas,'fatura-transacoes',{rodape:U.totalBRL(valores,3,2,{rotulo:rotuloTotal})});
}
