# Where Is the Money

Aplicação pessoal para investigar **para onde foi o dinheiro, o que mudou e quais lançamentos explicam isso**. Reúne bancos e cartões em relatórios locais, com categorias próprias, correções persistentes e rastreabilidade até o extrato.

## Abrir a aplicação

No PowerShell, a partir da raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
cd backend
..\.venv\Scripts\python.exe -m financas servir
```

Abra <http://127.0.0.1:8000>. O comando reaplica as views e publica os dados locais; **não chama a Pluggy**. Use `--porta 8001` para outra porta e `--banco caminho.duckdb` para outro banco. A configuração da fonte e a ingestão continuam descritas em [backend/README.md](backend/README.md) e [CONEXAO.md](CONEXAO.md).

`financas publicar --servir` também abre a edição local. Servir apenas os arquivos estáticos permite consultar os relatórios, mas não salvar personalizações. Não abra `index.html` por `file://`: o DuckDB-WASM precisa de HTTP. O motor WASM é carregado de uma versão fixa do jsDelivr, exigindo internet no primeiro carregamento.

## Investigar e revisar

- **Resumo:** gasto do período, variação, categorias e instituições; gráficos abrem os registros correspondentes.
- **Explorar gastos:** categorias, estabelecimentos, transações e matriz mensal, com filtros compartilhados.
- **Bancos e cartões:** gastos comparáveis, contas, cartões e datas de sincronização, movimento e posição.
- **Recorrências e parcelas:** sugestões a confirmar, custo anual estimado e parcelas futuras conhecidas.
- **Patrimônio:** posições monitoradas de contas, investimentos e dívida dos cartões, com datas e limitações de cobertura.
- **Revisão:** classificação em lote, mapeamentos da Pluggy, regras com prévia, aliases, compras e auditoria.
- **Ferramentas:** consultas SQL sobre a mesma publicação que alimenta os relatórios.

Os filtros de período, banco, conta e leitura das compras acompanham a navegação. O detalhamento preserva o recorte e permite voltar à análise anterior.

## O significado dos valores

**Por parcela** considera débitos de consumo na data do lançamento; parcelas futuras ficam fora do realizado. **Por compra** considera compras avulsas e agrupamentos de parcelas confirmados uma única vez, pelo total e data informados. Descrição e valor semelhantes não criam agrupamentos automáticos. Grupos incompletos exigem confirmação explícita.

O consolidado em BRL inclui somente BRL de origem ou conversão fornecida na moeda de uma conta BRL. Valores sem conversão comprovada permanecem na moeda original e tornam o consolidado parcial. Não há cotação presumida.

Transferências próprias, aplicações e pagamentos de fatura são excluídos do consumo pelas regras SQL. Créditos e estornos ficam na auditoria e não reduzem silenciosamente a medida de débitos de consumo. Gastos com cartão pertencem à instituição emissora.

Correção individual prevalece sobre regra da interface, regra TOML, mapeamento personalizado e mapeamento TOML, nesta ordem. Categorias, regras e ajustes são guardados em tabelas `usr_*`, separadas de `cfg_*`; reingerir e recarregar o TOML preserva as personalizações. Desfazer categoria e desfazer atributos restauram a correção anterior. Essencialidade pode ser definida por lançamento, independentemente da categoria.

Recorrências detectadas são sugestões. Parcelamentos não entram na detecção; ausência de cobrança não encerra uma assinatura. A confirmação tem abrangência de estabelecimento e banco, e as médias são calculadas por conta. Custo anual é estimativa baseada no histórico observado.

Saldo, investimento e dívida são posições, não gastos do período. Posições ausentes, antigas ou em outra moeda limitam o total monitorado. Um único retrato não gera uma tendência.

## Publicação e persistência

Cada `publicar` exporta as views numa transação para `frontend/dados/versoes/<versao>/`. O manifesto aponta para uma geração completa e é substituído atomicamente. Publicações anteriores permanecem disponíveis a abas abertas. Não apague versões enquanto houver leitores usando-as.

Se uma correção foi salva no DuckDB, mas a exportação falhou, a interface informa **salva, publicação pendente**. Use **Publicar novamente**; não repita a correção. Abas com revisão antiga recebem conflito e precisam atualizar antes de salvar.

A API escuta somente `127.0.0.1`, exige origem local e token nas gravações e serializa o acesso ao banco. Ela modifica personalizações, nunca payloads bancários. A CLI e a interface compartilham o arquivo DuckDB; um processo que estiver atualizando-o pode temporariamente impedir a edição.

## Verificação

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
cd ..
node --test frontend/tests/*.test.mjs
```

Os testes usam dados sintéticos. O plano e os critérios de aceite estão em [docs/planos/2026-09-17-investigacao.md](docs/planos/2026-09-17-investigacao.md).
