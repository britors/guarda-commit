# guarda-commit

[Português](#português) · [English](#english)

## Português

Plugin do [Claude Code](https://claude.com/claude-code) que revisa cada `git commit` e `git push` do Claude **antes** de rodar e bloqueia o que não deve ir para o repositório. A revisão é local, feita com expressões regulares e o próprio git: não gasta tokens do modelo.

### O que ele bloqueia

**No commit:**

- **Segredos nas linhas novas:** chaves privadas e chaves ou tokens da AWS, do GitHub, da Anthropic, da OpenAI, do Slack, do Google e do Stripe. Só as linhas acrescentadas são conferidas, e o aviso nunca repete o segredo.
- **Arquivos sensíveis:** `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `credentials.json`, `.npmrc` e outros. `.env.example` e `*.pub` passam.
- **Arquivos grandes:** acima de 5 MB.
- **Mensagem fora do padrão**, se você definir um (desligado por padrão).

**No push:**

- **Force push ou remoção** de branch protegido (`main` e `master`).
- **Push direto** em branch protegido, se você ligar (desligado por padrão).

O hook entende `git add -A && git commit`, `git commit -a`, `git -C <pasta>`, `cd <pasta> && git …` e mensagens escritas em heredoc. Quando bloqueia, explica o motivo ao Claude e pede que ele corrija o problema ou pergunte a você, sem contornar.

### Instalação

No Claude Code 2.1.275 ou mais novo, dentro de uma sessão:

```
/plugin install guarda-commit --marketplace britors/guarda-commit
```

Em versões anteriores:

```
/plugin marketplace add britors/guarda-commit
/plugin install guarda-commit@guarda-commit
```

Precisa de `python3` e `git` no PATH.

### Configuração

Crie `.guarda-commit.json` na raiz do repositório, ou `~/.claude/guarda-commit.json` para todos os projetos. O do repositório vence. Todas as chaves são opcionais:

```json
{
  "segredos": true,
  "arquivos_sensiveis": [".env", ".env.*", "*.pem", "*.key", "id_rsa"],
  "permitir_arquivos": [".env.example", "*.pub"],
  "tamanho_max_mb": 5,
  "branches_protegidas": ["main", "master", "release/*"],
  "bloquear_force_push": true,
  "bloquear_push_direto": false,
  "padrao_mensagem": "^(feat|fix|docs|chore)(\\(.+\\))?: "
}
```

Uma lista na configuração substitui a lista padrão inteira.

**Falso positivo?** Acrescente o comentário `guarda-commit: ignorar` na linha, ou ajuste a configuração.

**Precisa mesmo de um force push?** Rode o comando você mesmo, no terminal. O hook só revisa os comandos do Claude.

### Estrutura

```
.claude-plugin/plugin.json       manifesto
.claude-plugin/marketplace.json  marketplace de um plugin só
hooks/hooks.json                 registra o hook PreToolUse no Bash
hooks/guarda.py                  a revisão
tests/test_guarda.py             testes com repositórios temporários
```

Para rodar os testes: `python3 -m unittest discover -s tests`.

## English

[Claude Code](https://claude.com/claude-code) plugin that checks every `git commit` and `git push` Claude runs **before** it happens, and blocks what shouldn't reach the repository. The check runs locally with regular expressions and git itself, so it uses no model tokens.

- **Commit:** secrets in added lines (private keys; AWS, GitHub, Anthropic, OpenAI, Slack, Google and Stripe keys or tokens), sensitive files (`.env`, `*.pem`, `id_rsa`…), files over 5 MB, and optionally a commit message pattern.
- **Push:** force push or deletion of protected branches (`main`, `master`), and optionally any direct push to them.
- Understands `git add -A && git commit`, `commit -a`, `git -C`, `cd … &&` and heredoc messages. Secrets are never echoed back.

Install with `/plugin install guarda-commit --marketplace britors/guarda-commit`. Configure with `.guarda-commit.json` in the repository root or `~/.claude/guarda-commit.json` (keys above). Mark a false positive with a `guarda-commit: ignorar` comment on the line.

## Licença / License

[GPL-3.0](LICENSE)
