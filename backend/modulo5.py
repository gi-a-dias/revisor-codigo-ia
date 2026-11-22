"""Cliente do Módulo 5 (Agente de Curadoria de Tendências Tecnológicas).

Sugere leituras sobre os temas dos achados de uma revisão.
"""
import os
from collections import Counter

import requests

from github_pr import ErroIntegracao

URL_PADRAO = (
    "https://agente-tendencias-tecnologicas-fyd3bzerc9a2cqcu"
    ".chilecentral-01.azurewebsites.net"
)

TEMAS = {
    "Segurança": "boas práticas de segurança em código Python",
    "Code smell": "refatoração e code smells em Python",
    "Testes": "testes automatizados em Python",
    "Qualidade": "qualidade de código em Python",
}


def url_base():
    return (os.getenv("MODULO5_URL") or URL_PADRAO).strip().rstrip("/")


def montar_pergunta(relatorio):
    categorias = Counter(item["categoria"] for item in relatorio["achados"])
    temas = [TEMAS[c] for c, _ in categorias.most_common() if c in TEMAS][:2]

    if "Arquitetura" in categorias:
        temas.append(f"arquitetura {relatorio['arquitetura']} e dependências entre camadas")

    if not temas:
        temas = ["boas práticas de code review"]

    return "Quais são os artigos recentes sobre " + " e ".join(temas) + "?"


def buscar_leitura(pergunta):
    try:
        resposta = requests.post(
            url_base() + "/consultas",
            json={"pergunta": pergunta},
            timeout=(5, 45),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ErroIntegracao("Módulo 5 indisponível ou demorou demais.") from None

    if not 200 <= resposta.status_code < 300:
        raise ErroIntegracao(f"Módulo 5 respondeu HTTP {resposta.status_code}.")

    try:
        return resposta.json()
    except ValueError:
        raise ErroIntegracao("Módulo 5 retornou uma resposta inválida.") from None
