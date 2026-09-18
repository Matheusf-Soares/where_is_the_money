import test from 'node:test';
import assert from 'node:assert/strict';
import {acao,tratarClique,tratarSubmit,limparAcoes} from '../js/ui.mjs';
// Árvore DOM mínima: closest caminha pelos ancestrais como o navegador.
function elemento(tagName,parentElement=null,dataset={}){return {tagName,parentElement,dataset,closest(seletor){for(let el=this;el;el=el.parentElement)if(el.dataset.action&&(seletor==='[data-action]'||seletor==='button[data-action]'&&el.tagName==='BUTTON'))return el;return null;}};}
test('cliques em formulário, input ou botão de submit não disparam a ação do form; submit chama uma vez',async()=>{limparAcoes();const chamadas=[];const form=elemento('FORM',null,{action:acao(event=>chamadas.push(event.target.tagName))}),input=elemento('INPUT',form),submit=elemento('BUTTON',form);for(const target of [form,input,submit])await tratarClique({target});assert.deepEqual(chamadas,[]);await tratarSubmit({target:form,preventDefault(){}});assert.deepEqual(chamadas,['FORM']);});
test('botão de ação continua clicável pelo filho e não usa a ação do form ancestral',async()=>{limparAcoes();let forms=0,botoes=0;const form=elemento('FORM',null,{action:acao(()=>forms++)}),button=elemento('BUTTON',form,{action:acao(()=>botoes++)}),span=elemento('SPAN',button);await tratarClique({target:span});assert.equal(botoes,1);assert.equal(forms,0);});
