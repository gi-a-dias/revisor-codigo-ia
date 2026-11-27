"""Cliente do Módulo 2 (GitHub Sync).

O Módulo 2 indexa os repositórios e pull requests dos projetos da plataforma.
O revisor usa só leitura (GET): lista os PRs sincronizados para o usuário
escolher um e revisá-lo, sem precisar colar o link.

A API do Módulo 2 exige o JWT do Módulo 1. O revisor obtém esse token com uma
conta de serviço da plataforma (MODULO2_EMAIL e MODULO2_SENHA, só em variáveis
de ambiente) e o reaproveita até perto de expirar.
"""
import os
import re
import time

import requests

from github_pr import ErroIntegracao

URL_PADRAO = "https://ai-platform-github-service-eduardo-frapb8fbbcd0bfdm.brazilsouth-01.azurewebsites.net"
PADRAO_UUID = re.compile(r"[0-9a-fA-F-]{36}")
PADRAO_REPOSITORIO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
MAX_PAGINAS = 5

_token = {"valor": None, "expira_em": 0.0}


def url_base():
    return (os.getenv("MODULO2_URL") or URL_PADRAO).strip().rstrip("/")


def validar_project_id(valor):
    if valor in (None, ""):
        return None
    if not isinstance(valor, str) or not PADRAO_UUID.fullmatch(valor.strip()):
        raise ValueError("project_id inválido.")
    return valor.strip()


def _obter_token(renovar=False):
    if not renovar and _token["valor"] and time.time() < _token["expira_em"]:
        return _token["valor"]

    email = os.getenv("MODULO2_EMAIL", "").strip()
    senha = os.getenv("MODULO2_SENHA", "")

    if not email or not senha:
        raise ErroIntegracao("Configure MODULO2_EMAIL e MODULO2_SENHA para usar o Módulo 2.")

    try:
        resposta = requests.post(
            url_base() + "/api/v1/platform/auth/token",
            json={"email": email, "password": senha},
            headers={"Accept": "application/json"},
            timeout=(5, 20),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ErroIntegracao("Módulo 2 indisponível ou demorou demais.") from None

    if resposta.status_code == 401:
        raise ErroIntegracao("Módulo 2 recusou o login da conta de serviço (confira e-mail e senha).")

    if resposta.status_code != 200:
        raise ErroIntegracao(f"Login no Módulo 2 respondeu HTTP {resposta.status_code}.")

    try:
        dados = resposta.json()
        valor = dados["access_token"]
        validade = int(dados.get("expires_in") or 300)
    except (ValueError, KeyError, TypeError):
        raise ErroIntegracao("Módulo 2 retornou um token inválido.") from None

    # Renova um minuto antes de expirar.
    _token["valor"] = valor
    _token["expira_em"] = time.time() + max(30, validade - 60)
    return valor


def _get(caminho, params=None):
    for tentativa in range(2):
        token = _obter_token(renovar=tentativa > 0)

        try:
            resposta = requests.get(
                url_base() + caminho,
                params=params,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=(5, 20),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise ErroIntegracao("Módulo 2 indisponível ou demorou demais.") from None

        # Token expirado ou revogado: pede outro uma vez.
        if resposta.status_code == 401 and tentativa == 0:
            continue
        break

    if not 200 <= resposta.status_code < 300:
        raise ErroIntegracao(f"Módulo 2 respondeu HTTP {resposta.status_code}.")

    try:
        return resposta.json()
    except ValueError:
        raise ErroIntegracao("Módulo 2 retornou uma resposta inválida.") from None


def _repositorios_brutos():
    dados = _get("/api/v1/repositories")
    if isinstance(dados, dict):  # caso a lista venha paginada
        dados = dados.get("results", [])
    return [r for r in dados if isinstance(r, dict)]


def _nome_completo(repo):
    nome = repo.get("full_name") or f"{repo.get('owner', '')}/{repo.get('name', '')}"
    return nome if PADRAO_REPOSITORIO.fullmatch(nome or "") else None


def listar_repositorios(project_id=None):
    project_id = validar_project_id(project_id)
    repositorios = []

    for repo in _repositorios_brutos():
        if project_id and str(repo.get("project_id") or "").lower() != project_id.lower():
            continue
        repositorios.append({
            "id": repo.get("id"),
            "repositorio": _nome_completo(repo),
            "project_id": repo.get("project_id"),
            "branch_padrao": repo.get("default_branch"),
        })

    return repositorios


def listar_pull_requests(project_id=None, apenas_abertos=False):
    """PRs sincronizados pelo Módulo 2, já com o link do GitHub para revisar."""
    project_id = validar_project_id(project_id)
    repositorios = _repositorios_brutos()

    # O campo "repository" do PR pode vir como nome completo, nome curto ou id.
    por_chave = {}
    for repo in repositorios:
        completo = _nome_completo(repo)
        for chave in (completo, repo.get("name"), repo.get("id")):
            if chave not in (None, ""):
                por_chave[str(chave).lower()] = repo

    prs, pagina = [], 1
    while pagina <= MAX_PAGINAS:
        dados = _get("/api/v1/pull-requests", {"page": pagina})
        resultados = dados.get("results", []) if isinstance(dados, dict) else dados
        prs.extend(p for p in resultados if isinstance(p, dict))
        if not isinstance(dados, dict) or not dados.get("next"):
            break
        pagina += 1

    lista = []
    for pr in prs:
        referencia = str(pr.get("repository") or "")
        repo = por_chave.get(referencia.lower())

        if project_id and (
            not repo or str(repo.get("project_id") or "").lower() != project_id.lower()
        ):
            continue

        estado = str(pr.get("state") or "").lower()
        if apenas_abertos and estado != "open":
            continue

        completo = _nome_completo(repo) if repo else (
            referencia if PADRAO_REPOSITORIO.fullmatch(referencia) else None
        )
        numero = pr.get("number")

        lista.append({
            "repositorio": completo or referencia,
            "numero": numero,
            "titulo": pr.get("title"),
            "estado": estado,
            "autor": pr.get("author"),
            "atualizado_em": pr.get("updated_at"),
            "url": (
                f"https://github.com/{completo}/pull/{numero}"
                if completo and isinstance(numero, int)
                else None
            ),
        })

    lista.sort(key=lambda p: p.get("atualizado_em") or "", reverse=True)
    return lista
