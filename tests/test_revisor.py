import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient


temporario = tempfile.TemporaryDirectory()
configuracao = patch.dict(os.environ, {
    "DATABASE_PATH": str(Path(temporario.name) / "testes.db"),
    "GITHUB_TOKEN": "",
    "REVIEW_ACCESS_KEY": "",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "",
    "CORS_ORIGINS": "http://localhost:3000",
    "NOTIFICACOES_KEY": "",
    "NOTIFICACOES_PROJECT_ID": "",
    "NOTIFICACOES_URL": "",
    "ACESSO_ABERTO": "",
    "REPOS_COMENTARIO": "",
})
configuracao.start()
from app import app  # noqa: E402  (precisa vir depois de configurar o ambiente de teste)

unittest.addModuleCleanup(temporario.cleanup)
unittest.addModuleCleanup(configuracao.stop)

SHA = "a" * 40
PR_URL = "https://github.com/owner/repo/pull/1"
PR = {"title": "Exemplo", "head": {"sha": SHA, "repo": {"full_name": "fork/repo"}}}
AUTH = {"Authorization": "Basic " + base64.b64encode(b"revisor:senha").decode()}


class RevisorTest(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app)

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
        self.assertEqual(self.cliente.get("/api/health").json()["modulo"], 4)
        resposta = self.analisar("from app.repositories.usuario import salvar\neval('1')")
        self.assertEqual(resposta.status_code, 201)
        relatorio = resposta.json()
        self.assertFalse(relatorio["testes_executados"])
        self.assertEqual(
            {item["categoria"] for item in relatorio["achados"]},
            {"Arquitetura", "Segurança", "Testes"},
        )
        ids = {item["id"] for item in self.cliente.get("/api/historico").json()}
        self.assertIn(relatorio["id"], ids)

    def test_entrada_invalida_e_limites(self):
        for valor in ("", 123, "https://github.com/owner/../pull/1"):
            with self.subTest(valor=valor):
                resposta = self.analisar(pr_url=valor)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("Use um link", resposta.json()["erro"])
        self.assertEqual(self.analisar("x" * 100001).status_code, 400)
        self.assertEqual(self.analisar("x" * 500001).status_code, 413)
        bruto = json.dumps({"arquivos": [{"caminho": "a.py", "conteudo": "\ud800"}]})
        resposta = self.cliente.post(
            "/api/analisar", content=bruto.encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(self.analisar("def x(").status_code, 201)

    @patch("github_pr.github")
    def test_pr_fork_e_codificacao_python(self, github):
        github.side_effect = self.respostas_pr()
        resposta = self.analisar(pr_url=PR_URL)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["pr"]["sha"], SHA)
        self.assertIn("/repos/fork/repo/contents/src/controllers/com%20espa%C3%A7o.py",
                      github.call_args_list[2].args[0])
        self.assertIn("Arquitetura", {x["categoria"] for x in resposta.json()["achados"]})

    @patch("github_pr.github")
    def test_pr_alterado_e_resposta_invalida_do_github(self, github):
        github.side_effect = self.respostas_pr("b" * 40)
        resposta = self.analisar(pr_url=PR_URL)
        self.assertEqual(resposta.status_code, 502)
        self.assertIn("mudou durante a leitura", resposta.json()["erro"])
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
        url = f"/api/revisoes/{resposta.json()['id']}/comentar"
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
        self.assertEqual(repetida.json(), resposta.json())
        github.assert_not_called()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "token", "ACESSO_ABERTO": "1"})
    @patch("github_pr.github")
    def test_acesso_aberto_dispensa_login_e_restringe_comentarios(self, github):
        # Sem senha e com token: não bloqueia, porque o acesso aberto foi pedido.
        self.assertEqual(self.cliente.get("/api/historico").status_code, 200)

        # PR de um repositório de terceiros: analisa, mas não comenta.
        github.side_effect = self.respostas_pr()
        analise = self.cliente.post("/api/analisar", json={"pr_url": PR_URL})
        self.assertEqual(analise.status_code, 201)
        github.reset_mock()
        recusa = self.cliente.post(f"/api/revisoes/{analise.json()['id']}/comentar")
        self.assertEqual(recusa.status_code, 403)
        github.assert_not_called()

        # PR da conta da equipe (padrão de REPOS_COMENTARIO): publica.
        pr_equipe = "https://github.com/gi-a-dias/revisor-codigo-ia/pull/8"
        github.side_effect = self.respostas_pr()
        analise = self.cliente.post("/api/analisar", json={"pr_url": pr_equipe})
        self.assertEqual(analise.status_code, 201)
        github.side_effect = [PR, {"html_url": pr_equipe + "#review"}]
        publicada = self.cliente.post(f"/api/revisoes/{analise.json()['id']}/comentar")
        self.assertEqual(publicada.status_code, 201)

    def test_repositorios_autorizados_para_comentar(self):
        from app import repositorio_autorizado

        with patch.dict(os.environ, {"REPOS_COMENTARIO": "gi-a-dias, SophiaBetoni/revisor_codigo_ia"}):
            self.assertTrue(repositorio_autorizado("https://github.com/GI-A-DIAS/qualquer/pull/1"))
            self.assertTrue(repositorio_autorizado("https://github.com/sophiabetoni/revisor_codigo_ia/pull/2"))
            self.assertFalse(repositorio_autorizado("https://github.com/sophiabetoni/outro/pull/2"))
            self.assertFalse(repositorio_autorizado("https://github.com/owner/repo/pull/1"))

    @patch.dict(os.environ, {"GITHUB_TOKEN": "token", "REVIEW_ACCESS_KEY": "senha"})
    @patch("github_pr.github")
    def test_publicacao_sem_confirmacao_nao_reenvia(self, github):
        from github_pr import ErroIntegracao

        github.side_effect = self.respostas_pr()
        analise = self.cliente.post("/api/analisar", json={"pr_url": PR_URL}, headers=AUTH)
        url = f"/api/revisoes/{analise.json()['id']}/comentar"
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
        self.assertEqual(resposta.json()["ia"]["texto"], "Revisão de teste")

        post.return_value.json.return_value = []
        resposta = self.analisar(usar_ia=True)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["ia"]["status"], "Indisponível")
        self.assertTrue(resposta.json()["achados"])

        post.return_value = Mock(status_code=503)
        self.assertIn("HTTP 503", self.analisar(usar_ia=True).json()["ia"]["texto"])

        post.side_effect = requests.Timeout()
        self.assertIn("demorou", self.analisar(usar_ia=True).json()["ia"]["texto"])
    def test_cors_libera_apenas_o_front_autorizado(self):
        permitida = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        resposta = self.cliente.options("/api/analisar", headers=permitida)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.headers["access-control-allow-origin"], "http://localhost:3000"
        )

        resposta = self.cliente.options(
            "/api/analisar", headers={**permitida, "Origin": "http://site-ruim.com"}
        )
        self.assertNotIn("access-control-allow-origin", resposta.headers)

    def test_post_de_origem_nao_autorizada_e_bloqueado(self):
        corpo = {"arquivos": [{"caminho": "a.py", "conteudo": "x = 1"}]}
        resposta = self.cliente.post(
            "/api/analisar", json=corpo, headers={"Origin": "http://site-ruim.com"}
        )
        self.assertEqual(resposta.status_code, 403)
        resposta = self.cliente.post(
            "/api/analisar", json=corpo, headers={"Origin": "http://localhost:3000"}
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(
            resposta.headers["access-control-allow-origin"], "http://localhost:3000"
        )

    @patch.dict(os.environ, {"REVIEW_ACCESS_KEY": "senha"})
    def test_erro_401_tambem_leva_cabecalho_cors(self):
        resposta = self.cliente.get(
            "/api/historico", headers={"Origin": "http://localhost:3000"}
        )
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(
            resposta.headers["access-control-allow-origin"], "http://localhost:3000"
        )
        self.assertNotIn("www-authenticate", resposta.headers)

    def test_json_malformado_retorna_400(self):
        resposta = self.cliente.post(
            "/api/analisar", content=b"{nao e json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("erro", resposta.json())

    def test_frontend_desligado_por_padrao(self):
        self.assertEqual(self.cliente.get("/script.js").status_code, 404)
        self.assertEqual(self.cliente.get("/").json()["modulo"], 4)

    @patch.dict(os.environ, {"SERVIR_FRONTEND": "1", "REVIEW_ACCESS_KEY": "senha"})
    def test_frontend_servido_abre_sem_senha_mas_api_continua_protegida(self):
        pagina = self.cliente.get("/")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("text/html", pagina.headers["content-type"])
        self.assertIn("ReviewLab", pagina.text)

        for arquivo in ("/script.js", "/style.css", "/tokens.css", "/config.js"):
            self.assertEqual(self.cliente.get(arquivo).status_code, 200, arquivo)

        self.assertEqual(self.cliente.get("/api/historico").status_code, 401)
        self.assertEqual(self.cliente.get("/docs").status_code, 401)
        self.assertEqual(
            self.cliente.post("/api/analisar", json={}).status_code, 401
        )

    @patch.dict(os.environ, {"SERVIR_FRONTEND": "1"})
    def test_frontend_nao_entrega_arquivos_fora_da_pasta(self):
        for caminho in (
            "/backend/app.py",
            "/../backend/app.py",
            "/%2e%2e/backend/app.py",
            "/..%2fbackend%2fapp.py",
        ):
            resposta = self.cliente.get(caminho)
            self.assertEqual(resposta.status_code, 404, caminho)
            self.assertNotIn("FastAPI", resposta.text)

    def test_post_da_propria_origem_e_aceito(self):
        corpo = {"arquivos": [{"caminho": "a.py", "conteudo": "x = 1"}]}
        resposta = self.cliente.post(
            "/api/analisar", json=corpo, headers={"Origin": "http://testserver"}
        )
        self.assertEqual(resposta.status_code, 201)

    # ---- Integração com o Módulo 6 (notificações e métricas) ----

    @patch.dict(os.environ, {"NOTIFICACOES_KEY": "chave-de-teste"})
    def test_notifica_modulo_6_ao_concluir_revisao(self):
        with patch("notificacoes.requests.post", return_value=Mock(status_code=200)) as envio:
            resposta = self.analisar("eval('1')", project_id="proj-1")

        self.assertEqual(resposta.status_code, 201)
        relatorio = resposta.json()
        self.assertEqual(relatorio["notificacao"]["status"], "enviada")

        envio.assert_called_once()
        chamada = envio.call_args.kwargs
        self.assertEqual(chamada["headers"]["X-Integration-Key"], "chave-de-teste")
        corpo = chamada["json"]
        self.assertEqual(corpo["event_id"], f"modulo4-review-{relatorio['id']}")
        self.assertEqual(relatorio["notificacao"]["event_id"], corpo["event_id"])
        self.assertEqual(corpo["scope"], "project")
        self.assertEqual(corpo["project_id"], "proj-1")
        self.assertEqual(corpo["source"], "code_review")
        self.assertEqual(corpo["type"], "review.completed")
        self.assertEqual(corpo["priority"], "critical")
        self.assertIsNone(corpo["link"])
        self.assertNotIn("chave-de-teste", resposta.text)

    def test_prioridade_e_texto_da_notificacao(self):
        from notificacoes import montar_notificacao, prioridade_da_revisao

        def achado(categoria, gravidade):
            return {"categoria": categoria, "gravidade": gravidade}

        self.assertEqual(prioridade_da_revisao([]), "low")
        self.assertEqual(prioridade_da_revisao([achado("Code smell", "Baixa")]), "low")
        self.assertEqual(prioridade_da_revisao([achado("Testes", "Média")]), "medium")
        self.assertEqual(prioridade_da_revisao([achado("Arquitetura", "Alta")]), "high")
        self.assertEqual(
            prioridade_da_revisao(
                [achado("Arquitetura", "Alta"), achado("Segurança", "Alta")]
            ),
            "critical",
        )

        relatorio = {
            "id": "abc",
            "arquitetura": "mvc",
            "achados": [achado("Segurança", "Alta"), achado("Testes", "Média")],
            "pr": {"numero": 7, "titulo": "Adiciona login", "url": PR_URL},
        }
        payload = montar_notificacao(relatorio, "proj-9")
        self.assertIn("PR #7", payload["title"])
        self.assertEqual(payload["link"], PR_URL)
        self.assertIn("1 crítico(s)", payload["body"])
        self.assertIn("1 médio(s)", payload["body"])

    @patch.dict(os.environ, {"NOTIFICACOES_KEY": "chave-de-teste"})
    def test_falha_do_modulo_6_nao_derruba_a_revisao(self):
        casos = (
            (requests.ConnectionError("fora do ar"), "indisponível"),
            (Mock(status_code=401), "Chave"),
            (Mock(status_code=422), "project_id"),
            (Mock(status_code=500), "500"),
        )

        for retorno, trecho in casos:
            with self.subTest(trecho=trecho):
                mock = {"side_effect": retorno} if isinstance(retorno, Exception) \
                    else {"return_value": retorno}

                with patch("notificacoes.requests.post", **mock):
                    resposta = self.analisar("eval('1')", project_id="proj-1")

                self.assertEqual(resposta.status_code, 201)
                notificacao = resposta.json()["notificacao"]
                self.assertEqual(notificacao["status"], "falhou")
                self.assertIn(trecho, notificacao["detalhe"])

    @patch.dict(os.environ, {"NOTIFICACOES_KEY": "chave-de-teste"})
    def test_sem_project_id_nao_envia(self):
        with patch("notificacoes.requests.post") as envio:
            resposta = self.analisar("x = 1")

        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["notificacao"]["status"], "sem_projeto")
        envio.assert_not_called()

    def test_sem_chave_de_integracao_nao_envia(self):
        with patch("notificacoes.requests.post") as envio:
            resposta = self.analisar("x = 1", project_id="proj-1")

        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["notificacao"]["status"], "nao_configurada")
        envio.assert_not_called()

    def test_project_id_invalido(self):
        for valor in (123, "", "   ", "x" * 101):
            with self.subTest(valor=valor):
                self.assertEqual(self.analisar(project_id=valor).status_code, 400)

    @patch.dict(os.environ, {"NOTIFICACOES_KEY": "chave-de-teste"})
    def test_reenvio_usa_o_mesmo_event_id(self):
        with patch("notificacoes.requests.post", return_value=Mock(status_code=200)) as envio:
            relatorio = self.analisar("x = 1", project_id="proj-1").json()
            reenvio = self.cliente.post(f"/api/revisoes/{relatorio['id']}/notificar")

        self.assertEqual(reenvio.status_code, 200)
        self.assertEqual(
            [chamada.kwargs["json"]["event_id"] for chamada in envio.call_args_list],
            [f"modulo4-review-{relatorio['id']}"] * 2,
        )
        self.assertEqual(
            self.cliente.post("/api/revisoes/nao-existe/notificar").status_code, 404
        )

    def test_metricas_para_o_dashboard(self):
        for _ in range(2):
            self.assertEqual(
                self.analisar("eval('1')", project_id="proj-metricas").status_code, 201
            )

        resposta = self.cliente.get("/api/metricas?project_id=proj-metricas&dias=7")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["total_revisoes"], 2)
        self.assertEqual(dados["por_prioridade"]["critical"], 2)
        self.assertEqual(dados["por_prioridade"]["medium"], 2)
        self.assertEqual(dados["total_achados"], 4)
        self.assertEqual(dados["por_categoria"], {"Segurança": 2, "Testes": 2})
        self.assertEqual(len(dados["revisoes_por_dia"]), 7)
        self.assertEqual(dados["revisoes_por_dia"][-1]["revisoes"], 2)
        self.assertEqual(len(dados["ultimas_revisoes"]), 2)
        self.assertEqual(dados["ultimas_revisoes"][0]["project_id"], "proj-metricas")

        vazio = self.cliente.get("/api/metricas?project_id=nao-existe").json()
        self.assertEqual(vazio["total_revisoes"], 0)
        self.assertEqual(len(vazio["revisoes_por_dia"]), 14)

        for consulta in ("dias=0", "dias=91", "dias=abc"):
            self.assertEqual(self.cliente.get(f"/api/metricas?{consulta}").status_code, 400)

    def test_metricas_publicas_so_trazem_agregados(self):
        self.assertEqual(self.analisar("eval('1')", project_id="proj-pub").status_code, 201)

        resposta = self.cliente.get("/api/dashboard/metricas?project_id=proj-pub&dias=7")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers["access-control-allow-origin"], "*")
        dados = resposta.json()
        self.assertEqual(dados["total_revisoes"], 1)
        self.assertEqual(dados["por_arquitetura"], {"multicamadas": 1})
        self.assertNotIn("ultimas_revisoes", dados)
        self.assertEqual(len(dados["revisoes_por_dia"]), 7)
        self.assertEqual(self.cliente.get("/api/dashboard/metricas?dias=0").status_code, 400)

    @patch.dict(os.environ, {"REVIEW_ACCESS_KEY": "senha"})
    def test_metricas_publicas_abrem_sem_senha_mas_o_resto_nao(self):
        self.assertEqual(self.cliente.get("/api/dashboard/metricas").status_code, 200)
        self.assertEqual(self.cliente.get("/api/metricas").status_code, 401)
        self.assertEqual(self.cliente.get("/api/historico").status_code, 401)
        self.assertEqual(self.cliente.post("/api/dashboard/metricas").status_code, 401)

    @patch.dict(os.environ, {"REVIEW_ACCESS_KEY": "senha"})
    def test_metricas_exigem_senha(self):
        self.assertEqual(self.cliente.get("/api/metricas").status_code, 401)
        self.assertEqual(self.cliente.get("/api/metricas", headers=AUTH).status_code, 200)
