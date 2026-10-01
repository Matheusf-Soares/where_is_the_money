// Prévia dos lançamentos pendentes, sem substituição do total oficial da fonte.
import * as C from './core.mjs';
import * as U from './ui.mjs';
import {tabelaExtrato,nomeCartao} from './extrato-fatura.mjs';
const e=C.escapeHTML;
export function panoramaAndamento(dados){
 const cartoes=dados.faturas_abertas?.length?dados.faturas_abertas:(dados.cobertura_faturas??[]).map(c=>({...c,liquido_conhecido_brl:null,qtd_lancamentos:0}));
 const nomes=[...new Set(cartoes.map(c=>c.instituicao))];
 const bancos=nomes.map(nome=>{const contas=cartoes.filter(c=>c.instituicao===nome);return {nome,cartoes:contas,total:C.somar(contas,'liquido_conhecido_brl'),quantidade:C.somar(contas,'qtd_lancamentos')??0};}).sort((a,b)=>(b.total??-Infinity)-(a.total??-Infinity)||a.nome.localeCompare(b.nome));
 return {cartoes,bancos,total:C.somar(cartoes,'liquido_conhecido_brl')};
}
export function telaAndamento(ctx){
 const p=panoramaAndamento(ctx.dados),fs=ctx.estado.faturas;
 const abrir=nome=>{fs.selecao=nome;ctx.render();ctx.focarDetalhes?.();};
 const lista=p.bancos.map(g=>U.botao(`<span class="fatura-banco">${U.bancoNome(g.nome)}<small>${g.quantidade?g.quantidade+' lançamentos pendentes':'Sem lançamentos associados com segurança'}</small></span><span class="fatura-valor">${C.brl(g.total)}<small>prévia parcial em BRL</small></span>`,()=>abrir(g.nome),'fatura-linha'+(fs.selecao===g.nome?' selecionada':''),`aria-pressed="${fs.selecao===g.nome}" aria-controls="fatura-detalhes" aria-label="Prévia de ${e(g.nome)}. Abrir detalhes"`)).join('');
 const total=U.botao(`<span>Total em andamento<small>Despesas − créditos conhecidos · parcial</small></span><span>${C.brl(p.total)}</span>`,()=>abrir('__total__'),'fatura-total'+(fs.selecao==='__total__'?' selecionada':''),`aria-pressed="${fs.selecao==='__total__'}" aria-controls="fatura-detalhes"`);
 return `<div class="faturas-layout"><section class="faturas-lista" aria-label="Faturas por banco">${total}<div class="faturas-cabecalho"><span>Banco</span><span>Em andamento</span></div>${lista||U.vazio('Ainda não há dados de cartões nesta publicação.')}<p class="sub">Vencimentos mensais e totais oficiais estão nas opções de mês do seletor.</p></section>${detalhes(ctx,p)}</div>`+U.aviso('Prévia parcial dos lançamentos pendentes conhecidos. Não é o total oficial a pagar: compras recentes, parcelas e ajustes podem faltar. Pagamentos de faturas ficam separados.',true);
}
function detalhes(ctx,p){
 const selecao=ctx.estado.faturas.selecao;
 if(!selecao)return `<section id="fatura-detalhes" class="fatura-detalhes fatura-espera" aria-labelledby="fatura-detalhes-titulo"><span class="fatura-ilustracao" aria-hidden="true">${U.icone('faturas')}</span><h2 id="fatura-detalhes-titulo" tabindex="-1">Detalhes da fatura</h2><p>Selecione um banco ou o Total para conferir a prévia em andamento.</p></section>`;
 const cartoes=selecao==='__total__'?p.cartoes:p.bancos.find(b=>b.nome===selecao)?.cartoes??[];
 const ids=new Set(cartoes.map(c=>c.id_conta));
 const todos=(ctx.dados.lancamentos_fatura_aberta??[]).filter(t=>ids.has(t.id_conta));
 const incluidos=todos.filter(t=>t.incluida_previa&&t.tipo_lancamento!=='pagamento');
 const pagamentos=todos.filter(t=>t.incluida_previa&&t.tipo_lancamento==='pagamento');
 const fora=todos.filter(t=>!t.incluida_previa);
 const fechar=U.botao(U.icone('fechar'),()=>{ctx.estado.faturas.selecao=null;ctx.render();},'icon','aria-label="Fechar detalhes da fatura"');
 const cab=`<div class="fatura-detalhes-topo"><div><h2 id="fatura-detalhes-titulo" tabindex="-1">${e(selecao==='__total__'?'Todos os bancos':selecao)}</h2><p class="sub">Detalhes da fatura · em andamento · prévia parcial · ${incluidos.length} despesas e créditos</p></div>${fechar}</div>`;
 const cards=cartoes.map(c=>`<div class="fatura-cartao"><div><strong>${e(c.instituicao)} · ${e(nomeCartao(c))}</strong><small>${c.ultima_data?'Último lançamento conhecido: '+C.dataBR(c.ultima_data):'Sem lançamentos recentes associados'}${c.coletado_em?' · consulta '+C.dataBR(c.coletado_em):''}</small></div><strong>${C.brl(c.liquido_conhecido_brl)}</strong></div>`).join('');
 const inconsistentes=cartoes.filter(c=>c.qtd_previsao_inconsistente>0);
 const aviso=inconsistentes.length?U.aviso('A previsão de período da fonte conflita com uma fatura já fechada em '+inconsistentes.map(c=>c.instituicao).join(', ')+'. Estes lançamentos continuam pendentes; não atribuímos um mês de vencimento à prévia.') : '';
 const semConversao=cartoes.some(c=>c.qtd_sem_conversao>0)?U.aviso('Há valores sem conversão comprovada para BRL. Confira as moedas originais no extrato.'):'';
 const falhas=(ctx.dados.cobertura_faturas??[]).filter(c=>ids.has(c.id_conta)&&c.estado==='falha');
 const erro=falhas.length?U.aviso('A última atualização falhou para '+falhas.map(c=>c.instituicao).join(', ')+'. A prévia usa o último extrato disponível.'):'';
 const tabela=incluidos.length?tabelaExtrato(ctx,incluidos,cartoes,{rotuloTotal:'Total da prévia · despesas − créditos'}):U.vazio('Ainda não há despesas ou créditos associados com segurança ao período em andamento.');
 const separados=pagamentos.length?`<details class="fatura-previa-note"><summary>Pagamentos de faturas · ${pagamentos.length} registros separados</summary><p class="sub">Podem quitar um ciclo anterior; não reduzem a prévia de novos gastos.</p>${tabelaExtrato(ctx,pagamentos,cartoes,{rotuloTotal:'Total de pagamentos identificados',somentePagamentos:true})}</details>`:'';
 const pendentes=fora.length?`<details class="fatura-previa-note"><summary>Fora da prévia · ${fora.length} lançamentos futuros, anteriores ou sem associação</summary><p class="sub">Não entram no total em andamento. A indicação de período é preservada para conferência.</p>${tabelaExtrato(ctx,fora,cartoes,{rotuloTotal:'Total dos lançamentos fora da prévia'})}</details>`:'';
 return `<section id="fatura-detalhes" class="fatura-detalhes" aria-labelledby="fatura-detalhes-titulo">${cab}${cards}${aviso}${semConversao}${erro}<div class="fatura-extrato">${tabela}</div>${separados}${pendentes}<p class="sub fatura-rodape">Prévia calculada no processamento dos dados. Somente lançamentos pendentes sem vínculo a fatura fechada, com recorte conservador do período. Limite utilizado não entra no cálculo.</p></section>`;
}
