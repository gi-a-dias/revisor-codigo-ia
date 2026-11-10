import base64
import binascii
import io
import os
import re
import tokenize
from urllib.parse import quote

import requests


class ErroIntegracao(Exception):
    def __init__(self, mensagem, *, rejeitado=False):
        super().__init__(mensagem)
        self.rejeitado = rejeitado


def github(caminho, metodo="GET", dados=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "RevisorCodigoMVP",
    }

    token = os.getenv("GITHUB_TOKEN", "").strip()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resposta = requests.request(
            metodo,
            f"https://api.github.com{caminho}",
            headers=headers,
            json=dados,
            timeout=(10, 15),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ErroIntegracao("GitHub indisponível ou demorou demais.")

    if resposta.status_code == 404:
        raise ErroIntegracao(
            "PR ou arquivo não encontrado. "
            "Repositório privado pode exigir token.",
            rejeitado=True,
        )

    if not 200 <= resposta.status_code < 300:
        raise ErroIntegracao(
            f"GitHub respondeu HTTP {resposta.status_code}. "
            "Confira permissões e limites da API.",
            rejeitado=400 <= resposta.status_code < 500 and resposta.status_code != 408,
        )

    try:
        return resposta.json()
    except ValueError:
        raise ErroIntegracao("GitHub retornou uma resposta inválida.")


def _sha(pr):
    try:
        sha = pr["head"]["sha"]
        if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha):
            return sha
    except (KeyError, TypeError):
        pass
    raise ErroIntegracao("GitHub retornou um commit inválido.")


def obter_sha(pr):
    return _sha(github(f"{pr['base']}/pulls/{pr['numero']}"))


def _decodificar_arquivo(arquivo, caminho):
    if not isinstance(arquivo, dict):
        raise ErroIntegracao("GitHub retornou um arquivo inválido.")

    if arquivo.get("type") != "file" or arquivo.get("encoding") != "base64":
        raise ValueError(f"Arquivo Python indisponível para análise: {caminho}")

    try:
        dados = base64.b64decode("".join(arquivo["content"].split()), validate=True)
    except (KeyError, AttributeError, TypeError, ValueError, binascii.Error):
        raise ErroIntegracao("GitHub retornou conteúdo de arquivo inválido.") from None

    try:
        codificacao, _ = tokenize.detect_encoding(io.BytesIO(dados).readline)
        return dados.decode(codificacao)
    except (SyntaxError, UnicodeError):
        raise ValueError(f"Codificação Python inválida em {caminho}.") from None


def carregar_pr(url):
    padrao = r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]{0,18})/?"
    resultado = re.fullmatch(padrao, url.strip()) if isinstance(url, str) else None

    if not resultado or resultado[2] in {".", ".."}:
        raise ValueError("Use um link como https://github.com/owner/repo/pull/1")

    dono, repositorio, numero = resultado.groups()
    base = f"/repos/{dono}/{repositorio}"
    endereco_pr = f"{base}/pulls/{numero}"

    pr = github(endereco_pr)
    sha = _sha(pr)
    alteracoes = github(endereco_pr + "/files?per_page=21")

    if not isinstance(alteracoes, list):
        raise ErroIntegracao("GitHub retornou uma lista de arquivos inválida.")
    if len(alteracoes) > 20:
        raise ValueError("Este MVP aceita PRs com até 20 arquivos alterados.")

    try:
        origem = pr["head"]["repo"]
        nome_origem = origem["full_name"] if origem else None
        titulo = pr["title"]
    except (KeyError, TypeError):
        raise ErroIntegracao("GitHub retornou metadados de PR inválidos.") from None

    if not nome_origem:
        raise ValueError("O repositório de origem do PR não está disponível.")
    if (
        not isinstance(nome_origem, str)
        or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", nome_origem)
        or nome_origem.split("/")[1] in {".", ".."}
        or not isinstance(titulo, str)
    ):
        raise ErroIntegracao("GitHub retornou metadados de PR inválidos.")

    arquivos = []
    total = 0

    for item in alteracoes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("filename"), str)
            or not isinstance(item.get("status"), str)
        ):
            raise ErroIntegracao("GitHub retornou uma alteração inválida.")

        caminho = item["filename"]
        if item["status"] == "removed" or not caminho.endswith(".py"):
            continue

        endereco = f"/repos/{nome_origem}/contents/{quote(caminho, safe='/')}?ref={sha}"
        conteudo = _decodificar_arquivo(github(endereco), caminho)
        total += len(conteudo.encode("utf-8"))

        if total > 100_000:
            raise ValueError("Limite de 100 KB de código por revisão.")

        arquivos.append({"caminho": caminho, "conteudo": conteudo})

    if _sha(github(endereco_pr)) != sha:
        raise ErroIntegracao("O PR mudou durante a leitura. Faça uma nova análise.")

    if not arquivos:
        raise ValueError("O PR não possui arquivos Python elegíveis.")

    return arquivos, {
        "url": url.strip(),
        "titulo": titulo,
        "sha": sha,
        "base": base,
        "numero": int(numero),
    }


def publicar_revisao(pr, texto):
    revisao = github(
        f"{pr['base']}/pulls/{pr['numero']}/reviews",
        metodo="POST",
        dados={"body": texto, "commit_id": pr["sha"], "event": "COMMENT"},
    )
    if not isinstance(revisao, dict) or not isinstance(revisao.get("html_url"), str):
        raise ErroIntegracao("GitHub não confirmou o link da revisão.")
    return revisao["html_url"]