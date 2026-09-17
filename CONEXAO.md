# Passo a passo: destravar a conexão com a Pluggy

> Diagnóstico feito em **17/09/2026**, contra `https://api.pluggy.ai`, com as
> credenciais do seu `.env`. Tudo abaixo foi verificado com requisição real —
> não é suposição.

---

## O diagnóstico, em uma frase

**Suas credenciais estão corretas e a API responde.** O único endpoint recusado
é `GET /items` — e ele é recusado **por design, para todos os clientes da
Pluggy**. Não há nada para liberar.

### O que já está descartado

Rodei os endpoints um a um com a sua chave:

| Endpoint | Resposta | Leitura |
|---|---|---|
| `POST /auth` | **200** | credenciais válidas |
| `GET /connectors` | **200** · 1 conector | a apiKey é aceita |
| `GET /categories` | **200** · 130 categorias | a chave tem escopo de dados |
| `GET /items/{id}` | **404** | endpoint vivo, só não achou o id de teste |
| `GET /accounts` | **200** | liberado |
| `GET /v2/transactions` | **200** | liberado |
| `GET /investments` | **200** | liberado |
| `GET /webhooks` | **200** | liberado |
| **`GET /items`** (listar) | **401** | ← bloqueado permanentemente |

Ou seja: **não adianta** rotacionar o `CLIENT_SECRET`, trocar de ambiente,
mudar o cabeçalho ou mexer no `.env`. Os quatro estão comprovadamente certos.

---

## Por que listar items nunca vai ser liberado

A FAQ oficial da Pluggy diz textualmente:

> "Listing items is not available for security reasons, so that no data can
> leak across clients."

`GET /items` é desativado **por design**. Não é recurso da sua conta, não é
questão de plano, e abrir chamado no suporte será respondido com "é assim
mesmo". O `401` da v1 e o `LIST_ITEMS_FEATURE_NOT_ENABLED` da v2 não são um
bloqueio a remover: são a resposta final.

### O caminho oficial é guardar os `itemId` do seu lado

Verificado contra a API real:

```
GET /items/{id}   -> 404 ITEM_NOT_FOUND   <- endpoint vivo, só não achou o id de teste
GET /items        -> 401 Unauthorized     <- bloqueado permanentemente
```

Com o `itemId` em mãos, `/items/{id}`, `/accounts`, `/v2/transactions` e
`/investments` funcionam todos. Falta só descobrir os seus cinco.

---

## Passo a passo

### 1. Abra a aplicação certa no Dashboard

1. Entre em `dashboard.pluggy.ai` — conta de **desenvolvedor**, não a do
   `meu.pluggy.ai`. São logins separados.
2. Abra a aplicação cujo `clientId` começa com `cf2b`. É a do seu `.env`; se
   você tiver mais de uma, as outras não servem.
3. Confirme que o ambiente selecionado é **Desenvolvimento**.

### 2. Encontre os items e copie os ids

1. Procure a área de **Items** (pode aparecer como *Conexões* ou *Connections*)
   dentro da aplicação.
2. Você deve ver um item por instituição: PicPay, Santander, Nubank, Inter e
   Rico.
3. De cada um, copie o **id**: um UUID no formato
   `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.
4. Anote junto de qual instituição é cada um — você vai precisar para revisar
   depois.

**Se a área de items não existir ou estiver vazia**, os items nunca foram
criados nesta aplicação. Crie um item com o conector **MeuPluggy (id 200)**,
autenticando com a sua conta do Meu Pluggy; o `itemId` aparece no momento da
criação. É a ponte entre os dois portais, descrita na seção 4 do `CLAUDE.md`.

### 3. Valide cada id antes de confiar nele

Para cada UUID copiado:

```bash
cd backend
python -m financas diagnostico --modo online --item <UUID>
```

- **200** com o nome da instituição → id certo.
- **404 ITEM_NOT_FOUND** → id errado, ou de outra aplicação.

> ⚠️ A flag `--item` **ainda não existe**. É parte da mudança de código listada
> em "O que falta no código", que eu implemento assim que você tiver os ids.

### 4. Grave os ids na configuração

Em `config/regras.toml`, que já está fora do git:

```toml
[[item]]
id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
observacao = "Nubank"

[[item]]
id = "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"
observacao = "Santander"
```

Um bloco por instituição. O `observacao` é só para você se localizar.

### 5. Rode a ingestão

```bash
cd backend
python -m financas ingerir --modo online
python -m financas frescor
python -m financas views
python -m financas publicar --servir
```

### 6. Saiba o que fazer quando um id morrer

Armadilha 8: **reautorizar uma instituição gera um `itemId` novo.** Quando isso
acontecer, `/items/{id}` passa a responder 404 e aquela instituição para de
trazer dado.

Os alarmes que você já tem cobrem o caso:

- `ingerir` reporta a falha daquela instituição e sai com **código 3**;
- `frescor` acusa a instituição parada e sai com **código 2**.

Aí basta repetir os passos 2 a 4 para a instituição afetada. Não é silencioso —
é exatamente o modo de falha que o projeto foi desenhado para gritar.

---

## O que falta no código

A ingestão começa em `cliente.listar_itens()`, que nunca vai funcionar contra a
API real. Falta:

1. Ler `[[item]]` do `regras.toml`, validando o formato UUID e falhando cedo.
2. `ClienteHttp.listar_itens()` buscar `/items/{id}` um por um, em vez de
   listar.
3. `ClienteFixtures` continuar lendo `items.json`, para o modo offline não
   mudar em nada.
4. Flag `--item` no `diagnostico`, para validar um id sem ingerir nada.
5. Mensagem de erro dedicada para `regras.toml` sem nenhum `[[item]]`, dizendo
   onde pegar os ids.

São mudanças pequenas e contidas: `criar_cliente()` continua sendo o único lugar
que decide entre online e offline. **Me avise que eu implemento** — não depende
de você ter os ids em mãos, só de você querer.

---

## Depois que a ingestão real rodar

Três conferências que só você pode fazer, porque dependem do **seu** extrato.

### A. Os padrões de fatura pegaram alguma coisa?

```sql
SELECT instituicao, descricao, valor,
       e_pagamento_de_fatura, e_transferencia_propria, e_aplicacao
FROM stg_transacoes
WHERE e_pagamento_de_fatura OR e_transferencia_propria OR e_aplicacao;
```

Se vier vazio, **nenhum filtro casou** e o seu total de gastos está inflado. Os
padrões em `config/regras.toml` são um chute informado — só o extrato real diz
se o Santander escreve `PAGTO CARTAO` ou outra coisa.

### B. O que escapou dos filtros?

Esta é a consulta que revela filtro faltando:

```sql
SELECT instituicao, descricao, valor FROM gastos
WHERE lower(descricao) LIKE '%pix%'
   OR lower(descricao) LIKE '%ted%'
   OR lower(descricao) LIKE '%fatura%'
   OR lower(descricao) LIKE '%aplic%'
ORDER BY valor DESC;
```

Transferência própria ou pagamento de fatura que sobrou em `gastos` é padrão que
ninguém escreveu ainda. Acrescente no TOML e rode `python -m financas views` —
**sem reingerir nada**.

Lacuna conhecida: faltam as contas que não usam CPF nem telefone como chave Pix
(Santander ↔ Nubank ↔ Rico, que provavelmente saem por TED ou chave aleatória).

### C. Confira o sinal do saldo de cartão

A view `patrimonio` assume que o `balance` de conta `CREDIT` é o valor
**devido, positivo**. Se alguma instituição devolver negativo, o sinal inverte e
o patrimônio fica inflado:

```sql
SELECT instituicao, nome, tipo, saldo
FROM stg_contas WHERE tipo = 'CREDIT' AND e_retrato_atual;
```

Todos devem ser **positivos**. Se algum vier negativo, me avise — é ajuste de
uma linha em `sql/marts/03_patrimonio.sql`.

---

## Uma boa notícia

`GET /categories` devolveu **130 categorias**, então a **categorização está
habilitada** na sua conta — o README supunha que talvez não estivesse, por ser
feature premium.

O de-para da fase 2 vai funcionar de verdade, e este comando roda **agora**,
mesmo sem os `itemId`, porque a taxonomia é lista de referência:

```bash
cd backend
python -m financas categorias --sincronizar --modo online --saida mapa.toml
```

Revise os grupos e cole o bloco no fim de `config/regras.toml`.
