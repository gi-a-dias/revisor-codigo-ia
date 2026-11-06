import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


temporario = tempfile.TemporaryDirectory()
configuracao = patch.dict(os.environ, {
    "DATABASE_PATH": str(Path(temporario.name) / "testes.db"),
    "GITHUB_TOKEN": "",
    "REVIEW_ACCESS_KEY": "",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "",
})
configuracao.start()
from app import app

unittest.addModuleCleanup(temporario.cleanup)
unittest.addModuleCleanup(configuracao.stop)

SHA = "a" * 40
PR_URL = "https://github.com/owner/repo/pull/1"
PR = {"title": "Exemplo", "head": {"sha": SHA, "repo": {"full_name": "fork/repo"}}}
AUTH = {"Authorization": "Basic " + base64.b64encode(b"revisor:senha").decode()}


class RevisorTest(unittest.TestCase):
    def setUp(self):
        self.cliente = app.test_client()

    def analisar(self, codigo="print(1)", **opcoes):
        return self.cliente.post("/api/analisar", json={
            "arquivos": [{"caminho": "src/controllers/exemplo.py", "conteudo": codigo}],
            **opcoes,
        })

    def respostas_pr(self, sha_final=SHA):
        conteudo = "# coding: latin-1\nfrom .. import repositories\n# café\n"
        return [
            PR,
            [{"filename": "src/controllers/com espaço.py", "status": "modified"}],
            {
                "type": "file", "encoding": "base64",
                "content": base64.b64encode(conteudo.encode("latin-1")).decode(),
            },
            {"head": {"sha": sha_final}},
        ]

    def test_pagina_health_analise_e_historico(self):
        self.assertEqual(self.cliente.get("/").status_code, 200)
        self.assertEqual(self.cliente.get("/api/health").json["modulo"], 4)
        resposta = self.analisar("from app.repositories.usuario import salvar\neval('1')")
        self.assertEqual(resposta.status_code, 201)
        relatorio = resposta.json
        self.assertFalse(relatorio["testes_executados"])
        self.assertEqual(
            {item["categoria"] for item in relatorio["achados"]},
            {"Arquitetura", "Segurança", "Testes"},
        )
        ids = {item["id"] for item in self.cliente.get("/api/historico").json}
        self.assertIn(relatorio["id"], ids)

    def test_entrada_invalida_e_limites(self):
        for valor in ("", 123, "https://github.com/owner/../pull/1"):
            with self.subTest(valor=valor):
                resposta = self.analisar(pr_url=valor)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("Use um link", resposta.json["erro"])
        self.assertEqual(self.analisar("x" * 100001).status_code, 400)
        self.assertEqual(self.analisar("x" * 500001).status_code, 413)
        self.assertEqual(self.analisar("\ud800").status_code, 400)
        self.assertEqual(self.analisar("def x(").status_code, 201)

    @patch("github_pr.github")
    def test_pr_fork_e_codificacao_python(self, github):
        github.side_effect = self.respostas_pr()
        resposta = self.analisar(pr_url=PR_URL)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json["pr"]["sha"], SHA)
        self.assertIn("/repos/fork/repo/contents/src/controllers/com%20espa%C3%A7o.py",
                      github.call_args_list[2].args[0])
        self.assertIn("Arquitetura", {x["categoria"] for x in resposta.json["achados"]})

    @patch("github_pr.github")
    def test_pr_alterado_e_resposta_invalida_do_github(self, github):
        github.side_effect = self.respostas_pr("b" * 40)
        resposta = self.analisar(pr_url=PR_URL)
        self.assertEqual(resposta.status_code, 502)
        self.assertIn("mudou durante a leitura", resposta.json["erro"])
        github.side_effect = None
        github.return_value = []
        self.assertEqual(self.analisar(pr_url=PR_URL).status_code, 502)


    @patch.dict(os.environ, {"GITHUB_TOKEN": "token"})
    def test_token_sem_senha_bloqueia_operacoes(self):
        self.assertEqual(self.cliente.get("/api/health").status_code, 200)
        self.assertEqual(self.cliente.get("/api/historico").status_code, 503)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "token", "REVIEW_ACCESS_KEY": "senha"})
    @patch("github_pr.github")
    def test_publicacao_autenticada_e_vinculada_ao_commit(self, github):
        github.side_effect = self.respostas_pr()
        self.assertEqual(self.cliente.get("/").status_code, 401)
        self.assertEqual(self.cliente.get("/api/historico").status_code, 401)
        self.assertEqual(self.cliente.get("/api/historico", headers=AUTH).status_code, 200)
        resposta = self.cliente.post("/api/analisar", json={"pr_url": PR_URL}, headers=AUTH)
        self.assertEqual(resposta.status_code, 201)
        url = f"/api/revisoes/{resposta.json['id']}/comentar"
        github.reset_mock()
        self.assertEqual(self.cliente.post(url).status_code, 401)
        github.assert_not_called()

        github.side_effect = [{"head": {"sha": "b" * 40}}]
        self.assertEqual(self.cliente.post(url, headers=AUTH).status_code, 409)

        github.side_effect = [PR, {"html_url": PR_URL + "#review"}]
        resposta = self.cliente.post(url, headers=AUTH)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(github.call_args.kwargs["dados"]["commit_id"], SHA)
        self.assertEqual(github.call_args.kwargs["dados"]["event"], "COMMENT")

        github.reset_mock()
        repetida = self.cliente.post(url, headers=AUTH)
        self.assertEqual(repetida.status_code, 200)
        self.assertEqual(repetida.json, resposta.json)
        github.assert_not_called()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "token", "REVIEW_ACCESS_KEY": "senha"})
    @patch("github_pr.github")
    def test_publicacao_sem_confirmacao_nao_reenvia(self, github):
        from github_pr import ErroIntegracao

        github.side_effect = self.respostas_pr()
        analise = self.cliente.post("/api/analisar", json={"pr_url": PR_URL}, headers=AUTH)
        url = f"/api/revisoes/{analise.json['id']}/comentar"
        github.side_effect = [PR, ErroIntegracao("Timeout")]
        self.assertEqual(self.cliente.post(url, headers=AUTH).status_code, 502)
        github.reset_mock()
        self.assertEqual(self.cliente.post(url, headers=AUTH).status_code, 409)
        github.assert_not_called()

    @patch.dict(os.environ, {"GEMINI_API_KEY": "chave", "GEMINI_MODEL": "modelo"})
    @patch("gemini.requests.post")
    def test_gemini_sucesso_e_degradacao(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {
            "status": "completed",
            "steps": [{"type": "model_output", "content": [
                {"type": "text", "text": "Revisão de teste"}
            ]}],
        }
        resposta = self.analisar(usar_ia=True)
        self.assertEqual(resposta.json["ia"]["texto"], "Revisão de teste")

        post.return_value.json.return_value = []
        resposta = self.analisar(usar_ia=True)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json["ia"]["status"], "Indisponível")
        self.assertTrue(resposta.json["achados"])

        post.return_value = Mock(status_code=503)
        self.assertIn("HTTP 503", self.analisar(usar_ia=True).json["ia"]["texto"])

        post.side_effect = requests.Timeout()
        self.assertIn("demorou", self.analisar(usar_ia=True).json["ia"]["texto"])