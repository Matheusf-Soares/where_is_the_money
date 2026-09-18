import {sqlLiteral} from './core.mjs';
const TABELAS_UI=['transacoes_analiticas','gastos_analiticos','compras','recorrencias_analiticas','qualidade_dados','stg_transacoes','stg_contas','stg_investimentos'];
const linhasArrow=t=>t.toArray().map(r=>Object.fromEntries(Object.entries(r.toJSON?r.toJSON():r).map(([k,v])=>[k,typeof v==='bigint'?Number(v):v])));
const CDN='https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/dist/';
let duck,engine,worker,conexao,sequencia=0;
export let manifesto=null;
export async function carregarSnapshot(){
 const rodada=++sequencia;
 const resposta=await fetch('dados/manifesto.json',{cache:'no-store'});
 if(!resposta.ok)throw new Error('Não foi possível abrir dados/manifesto.json. Execute python -m financas servir no backend.');
 const novo=await resposta.json();
 if(novo.versao_schema!==2||!novo.arquivos)throw new Error('Publicação antiga ou incompatível. Execute python -m financas servir para gerar o manifesto v2.');
 duck??=await import('https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm');
 const bundle=await duck.selectBundle({mvp:{mainModule:CDN+'duckdb-mvp.wasm',mainWorker:CDN+'duckdb-browser-mvp.worker.js'},eh:{mainModule:CDN+'duckdb-eh.wasm',mainWorker:CDN+'duckdb-browser-eh.worker.js'}});
 const url=URL.createObjectURL(new Blob([`importScripts(${JSON.stringify(bundle.mainWorker)});`],{type:'text/javascript'}));
 const nextWorker=new Worker(url),nextEngine=new duck.AsyncDuckDB(new duck.ConsoleLogger(duck.LogLevel.ERROR),nextWorker);
 URL.revokeObjectURL(url);
 let nextConnection;
 try{
  await nextEngine.instantiate(bundle.mainModule,bundle.pthreadWorker);
  nextConnection=await nextEngine.connect();
  for(const [nome,caminho] of Object.entries(novo.arquivos)){
   if(!/^[a-z_]+$/.test(nome)||!/^versoes\/[a-zA-Z0-9-]+\/[a-z_]+\.parquet$/.test(caminho))throw new Error('Caminho inválido no manifesto: '+nome);
   const arquivo=`${rodada}_${nome}.parquet`;
   await nextEngine.registerFileURL(arquivo,new URL('dados/'+caminho,location.href).href,duck.DuckDBDataProtocol.HTTP,false);
   const schema=(await nextConnection.query(`DESCRIBE SELECT * FROM read_parquet(${sqlLiteral(arquivo)})`)).toArray();
   const cols=schema.map(c=>{const key='"'+c.column_name.replaceAll('"','""')+'"';return /DECIMAL|BIGINT|HUGEINT/.test(c.column_type)?`${key}::DOUBLE AS ${key}`:/DATE|TIMESTAMP/.test(c.column_type)?`${key}::VARCHAR AS ${key}`:key;});
   await nextConnection.query(`CREATE VIEW ${nome} AS SELECT ${cols.join(',')} FROM read_parquet(${sqlLiteral(arquivo)})`);
  }
  const dataset={};for(const nome of TABELAS_UI){if(!novo.arquivos[nome])throw new Error('Publicação incompleta: tabela '+nome+' ausente. Execute python -m financas servir.');dataset[nome]=linhasArrow(await nextConnection.query('SELECT * FROM '+nome));}
  if(rodada!==sequencia){await nextConnection.close();await nextEngine.terminate();return false;}
  const anterior=engine,conn=conexao;
  engine=nextEngine;worker=nextWorker;conexao=nextConnection;manifesto=novo;
  if(conn)await conn.close();if(anterior)await anterior.terminate();
  return dataset;
 }catch(e){if(nextConnection)await nextConnection.close().catch(()=>{});await nextEngine.terminate().catch(()=>{});throw e;}
}
export async function consultar(sql){if(!conexao)throw new Error('Aguarde o carregamento dos dados.');return linhasArrow(await conexao.query(sql));}
export const api={get podeEditar(){return !!this.estado?.edicao&&!this.conflito&&!this.estado.publicacao_pendente&&(manifesto?.revisao===undefined||manifesto.revisao===this.estado.revisao);},conflito:false,estado:null,catalogo:{categorias:[],regras:[],mapas:[],aliases:[],compras:[]},erro:''};
export async function carregarAPI(){try{const e=await fetch('/api/estado',{cache:'no-store'});if(!e.ok)throw new Error();api.estado=await e.json();const c=await fetch('/api/catalogo',{cache:'no-store'});if(!c.ok)throw new Error();api.catalogo=await c.json();api.erro='';api.conflito=false;}catch{api.estado=null;api.erro='Edição indisponível neste servidor. Para classificar e revisar, execute python -m financas servir.';}}
export async function gravar(ajuste,caminho='/api/ajustes',metodo='PUT'){
 if(!api.estado?.edicao)throw new Error(api.erro||'Edição indisponível.');
 if(caminho!=='/api/publicar'&&!api.podeEditar)throw new Error('Atualize os dados ou publique a correção pendente antes de editar novamente.');
 const r=await fetch(caminho,{method:metodo,headers:{'Content-Type':'application/json','X-Financas-Token':api.estado.token,'If-Match':String(api.estado.revisao)},body:JSON.stringify(ajuste)});
 const dados=await r.json();
 if(!r.ok){const e=new Error(dados.erro||'Não foi possível salvar.');e.conflito=r.status===409;if(e.conflito)api.conflito=true;throw e;}
 if(dados.revisao!==undefined)api.estado.revisao=dados.revisao;if(dados.token)api.estado.token=dados.token;
 if(caminho!=='/api/regras/previa')api.estado.publicacao_pendente=!!dados.publicacao_pendente||dados.publicado===false;
 return dados;
}
