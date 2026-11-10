#!/usr/bin/env python3
"""Hook PreToolUse do guarda-commit: revisa git commit e git push antes de rodarem.

Recebe pela entrada padrão o JSON do Claude Code com o comando Bash. Se o
comando tem git commit ou git push, confere:

- commit: segredos nas linhas novas, arquivos sensíveis, arquivos grandes e,
  se configurado, o padrão da mensagem;
- push: force push e, se configurado, push direto em branches protegidas.

Bloqueia com código 2 e explica o motivo na saída de erro, que volta para o
Claude. A configuração fica em ~/.claude/guarda-commit.json e em
.guarda-commit.json na raiz do repositório, que vence.
"""

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PADRAO = {
    "segredos": True,
    "arquivos_sensiveis": [
        ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json", ".npmrc", ".pypirc",
    ],
    "permitir_arquivos": [".env.example", ".env.sample", ".env.template", "*.pub"],
    "tamanho_max_mb": 5,
    "branches_protegidas": ["main", "master"],
    "bloquear_force_push": True,
    "bloquear_push_direto": False,
    "padrao_mensagem": None,
}

SEGREDOS = [
    ("chave privada", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY"),
    ("chave da AWS", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("token do GitHub", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    ("chave da Anthropic", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("chave da OpenAI", r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    ("token do Slack", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("chave do Google", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("chave do Stripe", r"\b[rs]k_live_[0-9A-Za-z]{20,}"),
]
SEGREDOS_RX = [(rotulo, re.compile(rx)) for rotulo, rx in SEGREDOS]
IGNORAR_LINHA = "guarda-commit: ignorar"
LIMITE_LEITURA = 2 * 1024 * 1024
PONTUACAO = "();<>|&\n"
DICA = (
    "Não contorne o bloqueio: corrija o problema ou pergunte ao usuário como seguir. "
    "Falsos positivos se resolvem com o comentário \"guarda-commit: ignorar\" na linha "
    "ou em .guarda-commit.json na raiz do repositório."
)


def git(pasta, *args):
    r = subprocess.run(
        ["git", "-C", str(pasta), *args], capture_output=True, text=True, errors="replace"
    )
    return r.stdout if r.returncode == 0 else None


def lista_z(saida):
    return [s for s in (saida or "").split("\0") if s]


def config(topo):
    cfg = dict(PADRAO)
    for arq in (Path.home() / ".claude" / "guarda-commit.json", topo / ".guarda-commit.json"):
        try:
            cfg.update(json.loads(arq.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return cfg


def comandos(texto):
    """Divide a linha de comando em comandos simples, cada um uma lista de palavras."""
    lex = shlex.shlex(texto, posix=True, punctuation_chars=PONTUACAO)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    atual, todos = [], []
    for t in lex:
        if set(t) <= set(PONTUACAO):
            if atual:
                todos.append(atual)
            atual = []
        else:
            atual.append(t)
    if atual:
        todos.append(atual)
    return todos


def subcomando_git(palavras, pasta):
    """(pasta do repositório, subcomando, argumentos) se as palavras forem um comando git."""
    i = 0
    while i < len(palavras) and "=" in palavras[i] and not palavras[i].startswith("-"):
        i += 1  # variáveis de ambiente antes do comando
    if i >= len(palavras) or os.path.basename(palavras[i]) != "git":
        return None
    i += 1
    while i < len(palavras) and palavras[i].startswith("-"):
        if palavras[i] == "-C" and i + 1 < len(palavras):
            pasta = pasta / os.path.expanduser(palavras[i + 1])
            i += 2
        elif palavras[i] in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(palavras):
            i += 2
        else:
            i += 1
    if i >= len(palavras):
        return None
    return pasta, palavras[i], palavras[i + 1 :]


def opcoes_commit(args):
    todos = False
    mensagens, caminhos = [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            caminhos += args[i + 1 :]
            break
        if a in ("-m", "--message") and i + 1 < len(args):
            mensagens.append(args[i + 1])
            i += 1
        elif a.startswith("--message="):
            mensagens.append(a.split("=", 1)[1])
        elif a == "--all":
            todos = True
        elif a in ("--file", "--reuse-message", "--reedit-message", "--template", "--author", "--date") and i + 1 < len(args):
            i += 1
        elif a.startswith("-") and not a.startswith("--"):
            curtas = a[1:]
            for j, c in enumerate(curtas):
                if c == "a":
                    todos = True
                elif c == "m":
                    if curtas[j + 1 :]:
                        mensagens.append(curtas[j + 1 :])
                    elif i + 1 < len(args):
                        mensagens.append(args[i + 1])
                        i += 1
                    break
                elif c in "FCct":
                    if not curtas[j + 1 :]:
                        i += 1
                    break
        elif not a.startswith("-"):
            caminhos.append(a)
        i += 1
    return todos, mensagens, caminhos


def texto_mensagem(m):
    """Texto da mensagem; extrai o corpo de um heredoc. None se não der para saber."""
    h = re.search(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1\b", m, re.S)
    if h:
        return h.group(2)
    if "$(" in m or "`" in m:
        return None
    return m


def arquivos_do_commit(topo, pasta, todos, caminhos, adds):
    """Arquivos que o commit vai levar, relativos à raiz: os já preparados e os dos git add anteriores."""
    nomes = set(lista_z(git(topo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")))
    if todos:
        nomes |= set(lista_z(git(topo, "diff", "--name-only", "-z", "--diff-filter=ACMR")))
    if caminhos:
        nomes |= set(lista_z(git(pasta, "diff", "HEAD", "--name-only", "-z", "--diff-filter=ACMR", "--", *caminhos)))
    for pasta_add, args in adds:
        saida = git(pasta_add, "add", "--dry-run", *args) or ""
        nomes |= set(re.findall(r"^add '(.*)'$", saida, re.M))
    return nomes


def linhas_novas(topo, arquivos):
    """Linhas acrescentadas por arquivo: o diff para os que já existem no HEAD, o conteúdo inteiro para os novos."""
    em_head = set(lista_z(git(topo, "ls-tree", "-r", "--name-only", "-z", "HEAD")))
    resultado = {}
    antigos = sorted(a for a in arquivos if a in em_head)
    if antigos:
        diff = git(topo, "diff", "HEAD", "--no-color", "--no-ext-diff", "-U0", "--", *antigos) or ""
        atual = None
        for linha in diff.splitlines():
            if linha.startswith("+++ "):
                atual = linha[6:] if linha.startswith("+++ b/") else None
            elif linha.startswith("+") and atual:
                resultado.setdefault(atual, []).append(linha[1:])
    for a in arquivos:
        if a in em_head:
            continue
        try:
            if (topo / a).stat().st_size <= LIMITE_LEITURA:
                resultado[a] = (topo / a).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            pass
    return resultado


def casa(nome, padroes):
    return any(fnmatch.fnmatch(nome, p) for p in padroes)


def checar_commit(pasta, args, adds):
    topo = git(pasta, "rev-parse", "--show-toplevel")
    if not topo:
        return []
    topo = Path(topo.strip())
    cfg = config(topo)
    todos, mensagens, caminhos = opcoes_commit(args)
    arquivos = arquivos_do_commit(topo, pasta, todos, caminhos, adds)
    problemas = []
    for a in sorted(arquivos):
        nome = os.path.basename(a)
        if casa(nome, cfg["arquivos_sensiveis"]) and not casa(nome, cfg["permitir_arquivos"]):
            problemas.append(f"{a}: arquivo sensível, não deve ir para o repositório")
        try:
            tamanho = (topo / a).stat().st_size
        except OSError:
            continue
        if tamanho > cfg["tamanho_max_mb"] * 1024 * 1024:
            problemas.append(f"{a}: {tamanho / 1024 / 1024:.1f} MB, acima do limite de {cfg['tamanho_max_mb']} MB")
    if cfg["segredos"]:
        for a, linhas in sorted(linhas_novas(topo, arquivos).items()):
            achados = []
            for linha in linhas:
                if IGNORAR_LINHA in linha:
                    continue
                achados += [rotulo for rotulo, rx in SEGREDOS_RX if rx.search(linha) and rotulo not in achados]
            problemas += [f"{a}: possível {rotulo} numa linha nova" for rotulo in achados]
    if cfg["padrao_mensagem"] and mensagens:
        texto = texto_mensagem(mensagens[0])
        if texto is not None:
            titulo = (texto.strip().splitlines() or [""])[0]
            if not re.search(cfg["padrao_mensagem"], titulo):
                problemas.append(f'mensagem "{titulo}" fora do padrão {cfg["padrao_mensagem"]}')
    return problemas


def checar_push(pasta, args):
    topo = git(pasta, "rev-parse", "--show-toplevel")
    if not topo:
        return []
    cfg = config(Path(topo.strip()))
    forca = tudo = False
    posicionais = []
    for a in args:
        if a in ("--force", "--delete") or a.startswith("--force-with-lease"):
            forca = True
        elif a in ("--all", "--mirror", "--branches"):
            tudo = True
        elif a.startswith("-") and not a.startswith("--"):
            forca = forca or "f" in a[1:] or "d" in a[1:]
        elif not a.startswith("-"):
            posicionais.append(a)
    atual = (git(pasta, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    alvos = []
    for r in posicionais[1:]:
        if r.startswith("+"):
            forca, r = True, r[1:]
        if r.startswith(":"):
            forca = True  # apagar o branch remoto
        destino = r.split(":")[-1].removeprefix("refs/heads/")
        alvos.append(atual if destino == "HEAD" else destino)
    if not posicionais[1:] and "--tags" not in args:
        alvos.append(atual)
    protegidas = [b for b in alvos if casa(b, cfg["branches_protegidas"])]
    if tudo:
        protegidas.append("todos os branches")
    if not protegidas:
        return []
    alvo = ", ".join(protegidas)
    if forca and cfg["bloquear_force_push"]:
        return [f"force push ou remoção em branch protegido ({alvo}); se for intencional, o usuário deve rodar no terminal"]
    if cfg["bloquear_push_direto"]:
        return [f"push direto em branch protegido ({alvo}); crie um branch e abra um PR"]
    return []


def analisar(texto, cwd):
    problemas = []
    pasta = Path(cwd)
    adds = []
    for palavras in comandos(texto):
        if palavras[0] == "cd" and len(palavras) > 1:
            pasta = pasta / os.path.expanduser(palavras[1])
            continue
        sub = subcomando_git(palavras, pasta)
        if not sub:
            continue
        repo, nome, args = sub
        if nome == "add":
            adds.append((repo, args))
        elif nome == "commit":
            problemas += checar_commit(repo, args, adds)
        elif nome == "push":
            problemas += checar_push(repo, args)
    return problemas


def main():
    try:
        dados = json.load(sys.stdin)
    except ValueError:
        return 0
    comando = (dados.get("tool_input") or {}).get("command") or ""
    if dados.get("tool_name") != "Bash" or "git" not in comando:
        return 0
    try:
        problemas = analisar(comando, dados.get("cwd") or os.getcwd())
    except Exception as e:  # um erro do hook nunca deve travar o trabalho
        print(f"guarda-commit: erro interno ({e}); comando liberado.", file=sys.stderr)
        return 1
    if not problemas:
        return 0
    print("guarda-commit bloqueou o comando:", file=sys.stderr)
    for p in problemas:
        print(f"- {p}", file=sys.stderr)
    print(DICA, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
