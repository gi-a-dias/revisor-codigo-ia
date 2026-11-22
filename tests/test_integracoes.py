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
})
configuracao.start()
from app import app  # noqa: E402  (precisa vir depois de configurar o ambiente de teste)
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
