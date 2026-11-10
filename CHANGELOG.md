# Changelog

## 1.0.0 — 10/11/2026

- Hook `PreToolUse` que revisa `git commit` e `git push` vindos do Claude:
  - segredos nas linhas novas (chaves privadas, AWS, GitHub, Anthropic, OpenAI, Slack, Google, Stripe);
  - arquivos sensíveis (`.env`, `*.pem`, `id_rsa`…) e arquivos grandes;
  - force push e remoção de branch protegido;
  - opcional: push direto em branch protegido e padrão da mensagem de commit.
- Entende `git add` no mesmo comando, `commit -a`, `git -C`, `cd … &&` e mensagens em heredoc.
- Configuração em `~/.claude/guarda-commit.json` e `.guarda-commit.json`.
- Testes e CI.
