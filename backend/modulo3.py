"""Cliente do Módulo 3 (Ingestão e Organização de Artefatos).

Usa só rotas GET, como pedido pelo Módulo 3 (o POST de análise gasta IA deles).
A API deles não exige login.
"""
import os
import re
import unicodedata
from urllib.parse import quote

import requests

from github_pr import ErroIntegracao

URL_PADRAO = "https://modulo3-fhgjdpa6d5bbfvff.canadacentral-01.azurewebsites.net"
TIPOS_ARTEFATO = {"PDF", "MARKDOWN", "PNG", "JPEG"}
PADRAO_ID = re.compile(r"[A-Za-z0-9._-]{1,100}")

# Palavras que indicam cada estilo, já sem acento e em minúsculas.
ESTILOS = {
    "hexagonal": ("hexagonal", "ports and adapters", "portas e adaptadores"),
    "onion": ("onion", "cebola"),
    "clean": ("clean",),
    "mvc": ("mvc", "model-view-controller", "model view controller"),
    "multicamadas": ("multicamada", "camadas", "layered", "n-tier", "n tier"),
}


def url_base():
    return (os.getenv("MODULO3_URL") or URL_PADRAO).strip().rstrip("/")


def validar_id(valor, nome):
    if not isinstance(valor, str) or not PADRAO_ID.fullmatch(valor):
        raise ValueError(f"{nome} inválido.")
    return valor


def _get(caminho, params=None):
    try:
        resposta = requests.get(
            url_base() + caminho,
            params=params,
            headers={"Accept": "application/json"},
            timeout=(5, 20),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ErroIntegracao("Módulo 3 indisponível ou demorou demais.") from None

    if resposta.status_code == 404:
        raise ValueError("Item não encontrado no Módulo 3.")

    if not 200 <= resposta.status_code < 300:
        raise ErroIntegracao(f"Módulo 3 respondeu HTTP {resposta.status_code}.")

    try:
        return resposta.json()
    except ValueError:
        raise ErroIntegracao("Módulo 3 retornou uma resposta inválida.") from None


def listar_projetos():
    return _get("/projects/")


def listar_artefatos(project_id, search=None, tipo=None):
    validar_id(project_id, "project_id")
    params = {}

    if search:
        params["search"] = str(search)[:100]

    if tipo:
        if tipo not in TIPOS_ARTEFATO:
            raise ValueError("Tipo inválido. Use PDF, MARKDOWN, PNG ou JPEG.")
        params["artifact_type"] = tipo

    return _get(f"/projects/{quote(project_id)}/artifacts/", params or None)


def listar_versoes(project_id, artifact_id):
    validar_id(project_id, "project_id")
    validar_id(artifact_id, "artifact_id")
    return _get(
        f"/projects/{quote(project_id)}/artifacts/{quote(artifact_id)}/versions"
    )


def obter_analise(analysis_id):
    validar_id(analysis_id, "analysis_id")
    return _get(f"/analyses/{quote(analysis_id)}")


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def mapear_arquitetura(texto):
    """Converte o texto livre do Módulo 3 em um dos nossos estilos (ou None)."""
    if not isinstance(texto, str):
        return None

    alvo = _normalizar(texto)

    for estilo, palavras in ESTILOS.items():
        if any(palavra in alvo for palavra in palavras):
            return estilo

    return None


def resumir_analise(analise):
    """Campos úteis da análise, mais a arquitetura sugerida para o /api/analisar."""
    if not isinstance(analise, dict):
        raise ErroIntegracao("Módulo 3 retornou uma análise inválida.")

    arquitetura = analise.get("architecture")

    return {
        "status": analise.get("status"),
        "classification": analise.get("classification"),
        "confidence": analise.get("confidence"),
        "summary": analise.get("summary"),
        "architecture": arquitetura,
        "arquitetura_sugerida": mapear_arquitetura(arquitetura),
        "error_message": analise.get("error_message"),
    }
