import {limitesMes,mesesContexto} from './core.mjs';

export function mesesDoSeletor(dataReferencia,inicio){
 return [...new Set([...mesesContexto(dataReferencia),inicio.slice(0,7)])].sort().reverse();
}

export function selecionarMesResumo(estado,mes,dataReferencia){
 const periodo=limitesMes(mes);
 Object.assign(estado.filtros,periodo,{fim:mes===dataReferencia.slice(0,7)?dataReferencia:periodo.fim});
 estado.drill=null;
 estado.pagina=0;
 estado.selecionadas.clear();
}
