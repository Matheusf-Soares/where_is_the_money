# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Usuário único: o próprio titular das contas, que também é quem desenvolve e opera o
projeto. Não há multiusuário, contas de terceiros, nem plano de acesso por contador
ou parceiro. A pessoa que usa a interface é a mesma que autorizou os bancos no Open
Finance e que lê o código-fonte.

## Product Purpose

Consolidar transações de múltiplas instituições financeiras (bancos, cartões,
investimentos), conectadas via Open Finance pela API da Pluggy, em um único
repositório analítico local. O produto existe para responder perguntas que apps de
controle financeiro prontos não respondem bem porque engessam a categorização e não
permitem séries históricas customizadas:

- Quanto foi gasto por mês, por categoria e por estabelecimento?
- Quais assinaturas recorrentes estão ativas e quanto custam por ano?
- Quais categorias fugiram da média dos meses anteriores?
- Qual a evolução do patrimônio (contas + investimentos) ao longo do tempo?

Sucesso é conseguir responder essas perguntas rápido, sobre dado real e completo, sem
depender de categorização que o usuário não controla.

## Positioning

Nenhum app de controle financeiro pronto permite reescrever a regra de categorização,
manter histórico bruto auditável (raw sagrado) e consultar via SQL versionado. Este
projeto troca a conveniência de um app de prateleira pela propriedade completa do
dado e da lógica de negócio — a categorização é resolvida em camadas próprias sobre
o sinal da Pluggy, não aceita como está.

## Operating Context

- **Backend:** pipeline Python (3.11+) que autentica na Pluggy, ingere
  items → accounts → transactions, grava em DuckDB (raw → staging → marts), e
  publica as views em Parquet. Roda localmente, via CLI (`python -m financas ...`),
  tipicamente por execução manual ou agendada (cron), nunca em nuvem por enquanto.
- **Frontend:** interface estática local (sem build, sem framework, sem pacotes
  JS instalados) servida por `python -m financas servir` e lida via DuckDB-WASM.
  Não pode ser aberta por `file://`. Já está em escopo ativo de design — a nota no
  CLAUDE.md sobre frontend "fora de escopo" descreve a fase 2 (categorização) como
  prioridade paralela, não um bloqueio ao trabalho de interface, que já tem fase 3
  concluída e segue recebendo trabalho.
- **Telas atuais:** Resumo, Explorar gastos, Bancos e cartões, Faturas, Recorrências
  e parcelas, Patrimônio, Revisão, Ferramentas SQL.
- **Idioma e ambiente:** interface e código (nomes de tabela, views, variáveis,
  comentários) inteiramente em português. Uso pessoal, local, sem autenticação de
  usuário porque só existe um usuário.

## Capabilities and Constraints

- Dado financeiro real (extratos, saldos, faturas) nunca pode ser commitado ou
  aparecer em artefato de design, documentação, screenshot compartilhado ou teste.
  Testes e fixtures usam exclusivamente dados sintéticos (titular "Fulano de Tal",
  CPF `12345678909`, telefone `31900001111`).
- Tema é **dark-only** (`<meta name="color-scheme" content="dark">`), compromisso
  fixo do produto — não um estado transitório a "completar" com tema claro depois.
- Idioma é **português, fixo** — não há plano de internacionalização.
- Regras de negócio (filtros, de-paras, padrões de categorização) vivem em
  `config/regras.toml`, nunca hardcoded em SQL ou JS: um teste estrutural falha se
  um `.sql` versionado tiver `LIKE '...'` com literal ou nome de instituição fora
  de comentário.
- A camada raw é sagrada: nunca perde dado nem aplica regra de negócio. Toda decisão
  discutível (o que é gasto, o que é transferência própria, o que é ruído) vive em
  staging/marts, revisável sem reingestão.
- Fase 2 (categorização própria em 3 camadas sobre a categoria da Pluggy) está em
  andamento e corre em paralelo ao trabalho de frontend — não é uma dependência que
  bloqueia mudanças de interface.
- Fase 4 (migração para GCP com execução agendada) é hipótese futura, não compromisso
  atual; SQL de marts evita construções exclusivas do DuckDB quando há equivalente
  padrão, para não fechar essa porta.
- A API local de edição/revisão exige token e trata resposta 202 (correção salva,
  aguarda nova publicação) e 409 (conflito, exige recarga) como estados distintos que
  a interface precisa comunicar, não esconder atrás de um spinner genérico.

## Brand Commitments

- Nome do produto: **"Onde foi parar?"**, subtítulo "Investigação de gastos".
- Tagline: **"SEU DINHEIRO, EM PERSPECTIVA"**.
- Ícone/wordmark atual: seta ↗ ao lado do nome, na sidebar.
- Voz de copy já estabelecida: direta, em português, sem jargão de marketing —
  exemplos reais do produto: "Espaço pessoal e local", "Dados preservados. Decisões
  suas.", "Valores em reais quando há conversão disponível. Dados originais
  preservados."
- Tema dark-only e idioma português (ver Capabilities and Constraints) também contam
  como compromissos de marca, não só técnicos.
- Direção visual: **padrão da categoria** (dashboard financeiro), escolhido de
  propósito em 01/10/2026, com o **Mercury** como régua de acabamento. Convenção
  executada com rigor, sem peculiaridade contrabandeada.

## Evidence on Hand

Nenhum dado real, testemunho, case ou métrica pode ser usado como evidência em
qualquer artefato — este é um projeto pessoal sem clientes, e dado financeiro real
não pode vazar para fora do ambiente local (fica fora do git por `.gitignore`). Toda
demonstração visual ou de conteúdo deve usar dados sintéticos equivalentes aos das
fixtures de teste.

## Product Principles

1. **Propriedade do dado acima de conveniência.** Cada decisão de produto favorece
   controlar a regra de categorização e manter histórico auditável, mesmo que um app
   pronto resolvesse mais rápido.
2. **Raw é sagrado; staging e marts decidem.** A interface nunca deve exigir
   reingestão para corrigir uma regra de negócio — a correção vive em SQL versionado
   ou em `config/regras.toml`.
3. **Falhar alto, nunca calado.** O modo de falha que o produto combate é o
   silencioso (filtro que não casa, instituição que parou de atualizar, página que
   não foi buscada). A interface deve expor esse tipo de lacuna, não escondê-la atrás
   de um estado "tudo certo".
4. **Local e single-user por design, não por limitação atual.** Não introduzir
   autenticação, multiusuário, ou dependência de nuvem enquanto a fase 4 não for uma
   decisão explícita.
5. **O grão granular vence o agregado.** Onde a Pluggy/SQL já preserva o grão da
   transação, a interface deve preferir mostrar e explicar a transação individual a
   esconder atrás de um agregado mensal que não pode ser desfeito.
