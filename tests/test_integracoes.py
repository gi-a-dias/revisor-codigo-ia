import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

temporario = tempfile.TemporaryDirectory()
configuracao = patch.dict(os.environ, {
    "DATABASE_PATH": str(Path(temporario.name) / "integracoes.db"),
    "GITHUB_TOKEN": "",
    "REVIEW_ACCESS_KEY": "",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "",
    "CORS_ORIGINS": "http://localhost:3000",
    "NOTIFICACOES_KEY": "",
    "NOTIFICACOES_PROJECT_ID": "",
    "NOTIFICACOES_URL": "",
    "MODULO2_EMAIL": "servico@revisor.dev",
    "MODULO2_SENHA": "senha-de-teste-123",
})
configuracao.start()
from app import app  # noqa: E402  (precisa vir depois de configurar o ambiente de teste)
import modulo2  # noqa: E402
import modulo3  # noqa: E402
import modulo5  # noqa: E402

unittest.addModuleCleanup(temporario.cleanup)
unittest.addModuleCleanup(configuracao.stop)


def resposta(status=200, dados=None):
    return Mock(status_code=status, json=Mock(return_value=dados))


class Modulo3Test(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app)

    def test_mapeia_arquitetura_para_os_nossos_estilos(self):
        casos = {
            "Arquitetura Hexagonal (Ports and Adapters)": "hexagonal",
            "Clean Architecture": "clean",
            "Arquitetura em Camadas": "multicamadas",
            "MVC": "mvc",
            "Onion Architecture": "onion",
            "Microsserviços": None,
            None: None,
        }

        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(modulo3.mapear_arquitetura(texto), esperado)

    def test_analise_traz_arquitetura_sugerida(self):
        dados = {
            "status": "COMPLETED",
            "classification": "architecture_document",
            "confidence": 0.9,
            "summary": "Resumo",
            "architecture": "Clean Architecture",
        }

        with patch("modulo3.requests.get", return_value=resposta(200, dados)) as get:
            retorno = self.cliente.get("/api/modulo3/analises/abc-123")

        self.assertEqual(retorno.status_code, 200)
        self.assertEqual(retorno.json()["arquitetura_sugerida"], "clean")
        self.assertEqual(retorno.json()["classification"], "architecture_document")
        self.assertTrue(get.call_args.args[0].endswith("/analyses/abc-123"))

    def test_lista_projetos_e_artefatos_com_filtros(self):
        with patch("modulo3.requests.get", return_value=resposta(200, [])) as get:
            self.assertEqual(self.cliente.get("/api/modulo3/projetos").status_code, 200)
            retorno = self.cliente.get(
                "/api/modulo3/projetos/p1/artefatos?search=spec&tipo=PDF"
            )

        self.assertEqual(retorno.status_code, 200)
        self.assertEqual(
            get.call_args.kwargs["params"],
            {"search": "spec", "artifact_type": "PDF"},
        )

    def test_rejeita_ids_e_tipos_invalidos(self):
        with patch("modulo3.requests.get") as get:
            self.assertEqual(
                self.cliente.get("/api/modulo3/analises/a%3Fb%3D1").status_code, 400
            )
            self.assertEqual(
                self.cliente.get("/api/modulo3/projetos/p1/artefatos?tipo=EXE").status_code,
                400,
            )

        get.assert_not_called()

    def test_falhas_do_modulo3_viram_erro_claro(self):
        with patch("modulo3.requests.get", return_value=resposta(500)):
            self.assertEqual(self.cliente.get("/api/modulo3/projetos").status_code, 502)

        with patch("modulo3.requests.get", return_value=resposta(404)):
            self.assertEqual(self.cliente.get("/api/modulo3/analises/x").status_code, 400)

        with patch("modulo3.requests.get", side_effect=requests.Timeout):
            self.assertEqual(self.cliente.get("/api/modulo3/projetos").status_code, 502)

    def test_usa_apenas_get(self):
        with patch("modulo3.requests.get", return_value=resposta(200, [])), \
                patch("modulo3.requests.post") as post:
            self.cliente.get("/api/modulo3/projetos")

        post.assert_not_called()


class Modulo5Test(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app)

    def criar_revisao(self):
        retorno = self.cliente.post("/api/analisar", json={
            "arquivos": [{
                "caminho": "src/controllers/a.py",
                "conteudo": "from app.repositories import x\neval('1')\n",
            }],
            "arquitetura": "multicamadas",
        })
        return retorno.json()

    def test_monta_pergunta_pelos_temas_dos_achados(self):
        revisao = self.criar_revisao()
        pergunta = modulo5.montar_pergunta(revisao)

        self.assertIn("segurança", pergunta)
        self.assertIn("multicamadas", pergunta)

    def test_leitura_recomendada_chama_o_modulo5(self):
        revisao = self.criar_revisao()
        artigos = {"artigos": [{"titulo": "T", "link": "https://exemplo.com"}]}

        with patch("modulo5.requests.post", return_value=resposta(200, artigos)) as post:
            retorno = self.cliente.post(f"/api/revisoes/{revisao['id']}/leitura-recomendada")

        self.assertEqual(retorno.status_code, 200)
        self.assertEqual(retorno.json()["resposta"], artigos)
        self.assertIn("pergunta", post.call_args.kwargs["json"])
        self.assertTrue(post.call_args.args[0].endswith("/consultas"))

    def test_revisao_inexistente_e_falha_do_modulo5(self):
        self.assertEqual(
            self.cliente.post("/api/revisoes/nao-existe/leitura-recomendada").status_code,
            404,
        )

        revisao = self.criar_revisao()

        with patch("modulo5.requests.post", return_value=resposta(503)):
            retorno = self.cliente.post(f"/api/revisoes/{revisao['id']}/leitura-recomendada")

        self.assertEqual(retorno.status_code, 502)


PROJETO = "f092329c-0747-4b88-92f0-c3036786ce91"
REPOS = [
    {"id": 7, "project_id": PROJETO, "owner": "gi-a-dias", "name": "revisor-codigo-ia",
     "full_name": "gi-a-dias/revisor-codigo-ia", "default_branch": "main"},
    {"id": 9, "project_id": None, "owner": "outra", "name": "coisa",
     "full_name": "outra/coisa", "default_branch": "main"},
]
PRS_PAGINA = {"count": 3, "next": None, "results": [
    {"repository": "gi-a-dias/revisor-codigo-ia", "number": 8, "title": "integração",
     "state": "open", "author": "gi-a-dias", "updated_at": "2026-11-22T10:00:00Z"},
    {"repository": "coisa", "number": 2, "title": "outro", "state": "closed",
     "author": "x", "updated_at": "2026-11-20T10:00:00Z"},
    {"repository": "7", "number": 10, "title": "barra", "state": "merged",
     "author": "gi-a-dias", "updated_at": "2026-11-23T10:00:00Z"},
]}


class Modulo2Test(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app)
        modulo2._token.update(valor=None, expira_em=0.0)

    def token(self):
        return resposta(200, {"access_token": "jwt", "token_type": "Bearer", "expires_in": 900})

    @patch("modulo2.requests.get")
    @patch("modulo2.requests.post")
    def test_lista_prs_com_link_e_filtra_por_projeto(self, post, get):
        post.return_value = self.token()
        get.side_effect = [resposta(200, REPOS), resposta(200, PRS_PAGINA)]

        dados = self.cliente.get(f"/api/modulo2/pull-requests?project_id={PROJETO}").json()

        self.assertEqual(
            [(p["numero"], p["url"]) for p in dados],
            [
                (10, "https://github.com/gi-a-dias/revisor-codigo-ia/pull/10"),
                (8, "https://github.com/gi-a-dias/revisor-codigo-ia/pull/8"),
            ],
        )
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer jwt")
        self.assertEqual(post.call_args.kwargs["json"]["email"], "servico@revisor.dev")

        # Sem projeto, traz todos; o token fica em cache (não faz login de novo).
        get.side_effect = [resposta(200, REPOS), resposta(200, PRS_PAGINA)]
        todos = self.cliente.get("/api/modulo2/pull-requests").json()
        self.assertEqual(len(todos), 3)
        self.assertEqual(post.call_count, 1)

        get.side_effect = [resposta(200, REPOS), resposta(200, PRS_PAGINA)]
        abertos = self.cliente.get("/api/modulo2/pull-requests?abertos=true").json()
        self.assertEqual([p["numero"] for p in abertos], [8])

    @patch("modulo2.requests.get")
    @patch("modulo2.requests.post")
    def test_token_expirado_e_renovado_uma_vez(self, post, get):
        post.return_value = self.token()
        get.side_effect = [resposta(401), resposta(200, REPOS)]
        dados = self.cliente.get("/api/modulo2/repositorios").json()
        self.assertEqual(dados[0]["repositorio"], "gi-a-dias/revisor-codigo-ia")
        self.assertEqual(post.call_count, 2)

    @patch("modulo2.requests.post")
    def test_falhas_viram_erros_claros(self, post):
        post.return_value = resposta(401)
        falha = self.cliente.get("/api/modulo2/repositorios")
        self.assertEqual(falha.status_code, 502)
        self.assertIn("recusou o login", falha.json()["erro"])

        post.side_effect = requests.ConnectionError()
        self.assertEqual(self.cliente.get("/api/modulo2/repositorios").status_code, 502)

        self.assertEqual(
            self.cliente.get("/api/modulo2/repositorios?project_id=abc").status_code, 400
        )

        with patch.dict(os.environ, {"MODULO2_EMAIL": ""}):
            sem_conta = self.cliente.get("/api/modulo2/repositorios")
            self.assertEqual(sem_conta.status_code, 502)
            self.assertIn("MODULO2_EMAIL", sem_conta.json()["erro"])
