"""Testes do hook: cada caso cria um repositório temporário e roda o hook como o Claude Code."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "guarda.py"
# Segredos falsos montados em partes, para este arquivo não parecer conter um segredo.
CHAVE_AWS = "AKIA" + "Z" * 16
TOKEN_GITHUB = "ghp" + "_" + "a1" * 18
CHAVE_PRIVADA = "-----BEGIN " + "RSA PRIVATE KEY-----"


class Guarda(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.escrever("README.md", "oi\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "início")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def escrever(self, nome, texto):
        p = self.repo / nome
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto)

    def config(self, **kv):
        self.escrever(".guarda-commit.json", json.dumps(kv))

    def rodar(self, comando, cwd=None):
        entrada = {"tool_name": "Bash", "tool_input": {"command": comando}, "cwd": str(cwd or self.repo)}
        r = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(entrada), capture_output=True, text=True,
            env={**os.environ, "HOME": str(self.home)},
        )
        return r.returncode, r.stderr

    def assertBloqueia(self, comando, trecho, **kw):
        codigo, erro = self.rodar(comando, **kw)
        self.assertEqual(codigo, 2, erro)
        self.assertIn(trecho, erro)

    def assertLibera(self, comando, **kw):
        codigo, erro = self.rodar(comando, **kw)
        self.assertEqual(codigo, 0, erro)

    # Comandos que não são commit nem push
    def test_comando_comum(self):
        self.assertLibera("ls -la && echo git")

    def test_commit_limpo(self):
        self.escrever("a.py", "print(1)\n")
        self.git("add", "a.py")
        self.assertLibera('git commit -m "a"')

    # Segredos
    def test_segredo_preparado(self):
        self.escrever("a.py", f'chave = "{CHAVE_AWS}"\n')
        self.git("add", "a.py")
        self.assertBloqueia('git commit -m "a"', "a.py: possível chave da AWS")

    def test_segredo_nao_aparece_na_mensagem(self):
        self.escrever("a.py", f'chave = "{CHAVE_AWS}"\n')
        self.git("add", "a.py")
        _, erro = self.rodar('git commit -m "a"')
        self.assertNotIn(CHAVE_AWS, erro)

    def test_segredo_em_git_add_no_mesmo_comando(self):
        self.escrever("novo.txt", f"token {TOKEN_GITHUB}\n")
        self.assertBloqueia('git add -A && git commit -m "x"', "novo.txt: possível token do GitHub")

    def test_segredo_com_commit_a(self):
        self.escrever("README.md", f"oi\n{CHAVE_PRIVADA}\n")
        self.assertBloqueia('git commit -am "x"', "README.md: possível chave privada")

    def test_so_linhas_novas(self):
        self.escrever("velho.txt", f"{CHAVE_AWS}  # guarda-commit: ignorar\n")
        self.git("add", "velho.txt")
        self.git("commit", "-q", "-m", "velho")
        self.escrever("velho.txt", f"{CHAVE_AWS}  # guarda-commit: ignorar\nlinha nova\n")
        self.assertLibera('git commit -am "x"')

    def test_comentario_ignorar(self):
        self.escrever("a.py", f'exemplo = "{CHAVE_AWS}"  # guarda-commit: ignorar\n')
        self.git("add", "a.py")
        self.assertLibera('git commit -m "a"')

    def test_git_C_e_cd(self):
        self.escrever("a.py", f'k = "{CHAVE_AWS}"\n')
        self.git("add", "a.py")
        fora = self.repo.parent
        self.assertBloqueia(f'git -C {self.repo} commit -m "a"', "possível chave da AWS", cwd=fora)
        self.assertBloqueia(f'cd {self.repo} && git commit -m "a"', "possível chave da AWS", cwd=fora)

    # Arquivos sensíveis e grandes
    def test_env(self):
        self.escrever(".env", "SENHA=1\n")
        self.assertBloqueia("git add .env && git commit -m x", ".env: arquivo sensível")

    def test_env_example(self):
        self.escrever(".env.example", "SENHA=\n")
        self.assertLibera("git add .env.example && git commit -m x")

    def test_arquivo_grande(self):
        self.config(tamanho_max_mb=0.001)
        self.escrever("grande.bin", "x" * 5000)
        self.assertBloqueia("git add grande.bin && git commit -m x", "grande.bin: 0.0 MB, acima do limite")

    # Mensagem
    def test_padrao_mensagem(self):
        self.config(padrao_mensagem=r"^(feat|fix|docs): ")
        self.escrever("a.py", "1\n")
        self.git("add", "a.py")
        self.assertBloqueia('git commit -m "wip"', "fora do padrão")
        self.assertLibera('git commit -m "fix: corrige a"')

    def test_padrao_mensagem_heredoc(self):
        self.config(padrao_mensagem=r"^fix: ")
        self.escrever("a.py", "1\n")
        self.git("add", "a.py")
        heredoc = "git commit -m \"$(cat <<'EOF'\n{}\n\ncorpo\nEOF\n)\""
        self.assertBloqueia(heredoc.format("wip"), 'mensagem "wip"')
        self.assertLibera(heredoc.format("fix: ok"))

    # Push
    def test_force_push_main(self):
        self.assertBloqueia("git push --force origin main", "force push")
        self.assertBloqueia("git push -f", "force push")
        self.assertBloqueia("git push origin +main", "force push")
        self.assertBloqueia("git push origin :main", "force push")

    def test_force_push_em_branch_livre(self):
        self.assertLibera("git push --force-with-lease origin feature")

    def test_push_direto(self):
        self.assertLibera("git push origin main")
        self.config(bloquear_push_direto=True)
        self.assertBloqueia("git push origin main", "push direto")
        self.assertBloqueia("git push", "push direto")
        self.assertLibera("git push -u origin feature")
        self.assertLibera("git push origin v1.0")


if __name__ == "__main__":
    unittest.main()
