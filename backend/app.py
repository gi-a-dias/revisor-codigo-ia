import base64
import binascii
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from analisador import REGRAS, analisar
from gemini import consultar_ia
import modulo3
import modulo5
from github_pr import ErroIntegracao, carregar_pr, obter_sha, publicar_revisao
from notificacoes import (
    PRIORIDADES,
    contar_por_prioridade,
    notificar_revisao,
)


PASTA = Path(__file__).resolve().parent
load_dotenv(PASTA / ".env")

LIMITE_CORPO = 500_000

# Opcional: com SERVIR_FRONTEND=1 a própria API entrega a pasta frontend/,
# o que permite publicar tudo num único App Service. Desligado por padrão.
FRONTEND = (PASTA.parent / "frontend").resolve()

# Origens do front-end autorizadas a chamar esta API (separadas por vírgula).
ORIGENS_PERMITIDAS = [
    origem.strip().rstrip("/")
    for origem in (
        os.getenv("CORS_ORIGINS")
        or "http://127.0.0.1:3000,http://localhost:3000"
    ).split(",")
    if origem.strip()
]

app = FastAPI(title="Revisor de Código com IA — Módulo 4", version="1.0")

BANCO = Path(
    os.getenv("DATABASE_PATH") or str(PASTA / "revisoes.db")
)
BANCO.parent.mkdir(parents=True, exist_ok=True)


def ligado(variavel):
    return os.getenv(variavel, "").strip().lower() in {"1", "true", "sim", "yes"}


def servindo_frontend():
    return ligado("SERVIR_FRONTEND")


def acesso_aberto():
    """Com ACESSO_ABERTO=1 o site funciona sem login, mesmo com GITHUB_TOKEN."""
    return ligado("ACESSO_ABERTO")


def repositorio_autorizado(url_pr):
    """Com o acesso aberto, só estes repositórios recebem comentários do token.
    REPOS_COMENTARIO aceita donos ("gi-a-dias") ou repositórios ("dono/repo"),
    separados por vírgula. Padrão: a conta da equipe."""
    autorizados = {
        item.strip().strip("/").lower()
        for item in (os.getenv("REPOS_COMENTARIO") or "gi-a-dias").split(",")
        if item.strip()
    }
    partes = urlparse(url_pr).path.strip("/").lower().split("/")

    if len(partes) < 2:
        return False

    dono, repositorio = partes[0], partes[1]
    return dono in autorizados or f"{dono}/{repositorio}" in autorizados


def arquivo_frontend(caminho):
    """Resolve um arquivo dentro de frontend/ (nunca fora dela)."""
    alvo = (FRONTEND / (caminho or "index.html")).resolve()

    if alvo.is_dir():
        alvo = alvo / "index.html"

    if alvo.is_relative_to(FRONTEND) and alvo.is_file():
        return alvo

    return None


def erro(mensagem, status, headers=None):
    return JSONResponse({"erro": mensagem}, status_code=status, headers=headers)


def conectar():
    conexao = sqlite3.connect(BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


with closing(conectar()) as conexao, conexao:
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS revisoes (
            id TEXT PRIMARY KEY,
            criado_em TEXT NOT NULL,
            relatorio TEXT NOT NULL
        )
    """)

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS publicacoes (
            revisao_id TEXT PRIMARY KEY,
            url TEXT
        )
    """)


def salvar(relatorio):
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO revisoes VALUES (?, ?, ?)",
            (
                relatorio["id"],
                relatorio["criado_em"],
                json.dumps(relatorio, ensure_ascii=False),
            ),
        )


def buscar(identificador):
    with closing(conectar()) as conexao, conexao:
        linha = conexao.execute(
            "SELECT relatorio FROM revisoes WHERE id = ?",
            (identificador,),
        ).fetchone()

    return json.loads(linha["relatorio"]) if linha else None


def validar_arquivos(arquivos):
    if not isinstance(arquivos, list) or not 1 <= len(arquivos) <= 20:
        raise ValueError("Envie entre 1 e 20 arquivos Python.")

    caminhos = set()
    total = 0

    for arquivo in arquivos:
        if not isinstance(arquivo, dict):
            raise ValueError("Arquivo inválido.")

        caminho = arquivo.get("caminho")
        conteudo = arquivo.get("conteudo")

        if not isinstance(caminho, str) or not isinstance(conteudo, str):
            raise ValueError("Cada arquivo precisa de caminho e conteúdo.")

        caminho = caminho.replace("\\", "/").strip()
        arquivo["caminho"] = caminho

        if (
            not caminho.endswith(".py")
            or caminho.startswith("/")
            or ".." in caminho.split("/")
            or len(caminho) > 200
            or caminho in caminhos
        ):
            raise ValueError("Use caminhos relativos e únicos de arquivos .py.")

        caminhos.add(caminho)
        caminho.encode("utf-8")
        total += len(conteudo.encode("utf-8"))

    if total > 100_000:
        raise ValueError("Limite de 100 KB de código por revisão.")


def gerar_markdown(relatorio):
    linhas = [
        "# Revisão de código",
        "",
        f"Data: {relatorio['criado_em']}",
        f"Arquitetura: {relatorio['arquitetura']}",
        "",
    ]

    if relatorio["pr"]:
        linhas.extend([
            f"PR: {relatorio['pr']['url']}",
            f"Commit analisado: {relatorio['pr']['sha']}",
            "",
        ])

    linhas.extend(["## Achados", ""])

    for item in relatorio["achados"]:
        local = item["arquivo"]

        if item["linha"]:
            local += f":{item['linha']}"

        linhas.extend([
            f"### {item['gravidade']} — {item['titulo']}",
            f"Local: {local}",
            f"Categoria: {item['categoria']}",
            f"Sugestão: {item['sugestao']}",
            "",
        ])

    if not relatorio["achados"]:
        linhas.append("Nenhum achado pelas regras aplicadas.")

    linhas.extend([
        "",
        "## Especialista Virtual",
        "",
        relatorio["ia"]["texto"],
        "",
        "## Limitações",
        "",
        "- Análise simplificada de Python; pode gerar falsos positivos.",
        "- Testes não foram executados.",
        "- No PR, apenas arquivos alterados elegíveis foram analisados.",
        "- Arquitetura verificada por caminhos e imports.",
    ])

    return "\n".join(linhas)


def credenciais_basic(request):
    """Extrai usuário e senha do cabeçalho Authorization: Basic."""
    cabecalho = request.headers.get("authorization", "")
    esquema, _, valor = cabecalho.partition(" ")

    if esquema.lower() != "basic" or not valor:
        return None

    try:
        decodificado = base64.b64decode(valor.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None

    usuario, separador, senha = decodificado.partition(":")
    return (usuario, senha) if separador else None


# Rotas abertas direto no navegador (documentação). Só nelas o cabeçalho
# WWW-Authenticate é enviado, para o navegador pedir a senha. Nas chamadas
# do front-end (outra origem) quem pede a senha é a própria tela.
ROTAS_NAVEGADOR = {"/", "/docs", "/redoc", "/openapi.json"}
ROTAS_DOCUMENTACAO = {"/docs", "/redoc", "/openapi.json"}


def rota_publica(request):
    caminho = request.url.path

    if caminho == "/api/health":
        return True

    # Só contagens agregadas, para a página de gráficos embutida pelo Módulo 6.
    if caminho == "/api/dashboard/metricas" and request.method == "GET":
        return True

    # A página e seus arquivos precisam abrir sem senha para a tela de login
    # aparecer; a API continua protegida.
    return (
        servindo_frontend()
        and request.method == "GET"
        and not caminho.startswith("/api")
        and caminho not in ROTAS_DOCUMENTACAO
    )


@app.middleware("http")
async def verificar_acesso(request: Request, call_next):
    if request.method == "OPTIONS" or rota_publica(request) or acesso_aberto():
        return await call_next(request)

    senha = os.getenv("REVIEW_ACCESS_KEY", "").strip()
    if not senha:
        if os.getenv("GITHUB_TOKEN", "").strip():
            return erro("Configure REVIEW_ACCESS_KEY para usar GITHUB_TOKEN.", 503)
        return await call_next(request)

    credenciais = credenciais_basic(request)
    if (
        credenciais
        and credenciais[0] == "revisor"
        and hmac.compare_digest(
            credenciais[1].encode("utf-8"), senha.encode("utf-8")
        )
    ):
        return await call_next(request)

    headers = None
    if request.url.path in ROTAS_NAVEGADOR:
        headers = {
            "WWW-Authenticate": 'Basic realm="Revisor de Codigo", charset="UTF-8"'
        }

    return erro("Acesso restrito ao revisor.", 401, headers)


@app.middleware("http")
async def verificar_origem(request: Request, call_next):
    # Impede solicitações do navegador originadas de sites não autorizados.
    # Vale a origem do próprio serviço (comparada pelo host, que não muda atrás
    # de proxy) ou uma das listadas em CORS_ORIGINS.
    if request.method == "POST":
        origem = request.headers.get("origin")

        if (
            origem
            and origem.rstrip("/") not in ORIGENS_PERMITIDAS
            and urlparse(origem).netloc != request.headers.get("host", "")
        ):
            return erro("Origem da solicitação inválida.", 403)

    return await call_next(request)


# Adicionado por último para ficar na camada mais externa: assim até as
# respostas de erro (401, 403, 413) levam os cabeçalhos CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


async def ler_json(request):
    """Lê o corpo JSON respeitando o limite de tamanho. Retorna (dados, resposta_de_erro)."""
    declarado = request.headers.get("content-length")

    if declarado and declarado.isdigit() and int(declarado) > LIMITE_CORPO:
        return None, erro("Solicitação maior que o limite permitido.", 413)

    corpo = bytearray()
    async for pedaco in request.stream():
        corpo.extend(pedaco)

        if len(corpo) > LIMITE_CORPO:
            return None, erro("Solicitação maior que o limite permitido.", 413)

    try:
        return json.loads(bytes(corpo)), None
    except ValueError:
        return None, None


@app.get("/")
def inicio():
    if servindo_frontend():
        return FileResponse(FRONTEND / "index.html")

    return {
        "servico": "Revisor de Código com IA",
        "modulo": 4,
        "documentacao": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "modulo": 4}


@app.get("/api/historico")
def historico():
    with closing(conectar()) as conexao, conexao:
        linhas = conexao.execute(
            "SELECT relatorio FROM revisoes "
            "ORDER BY criado_em DESC LIMIT 20"
        ).fetchall()

    return [json.loads(linha["relatorio"]) for linha in linhas]


def processar_analise(dados):
    arquitetura = dados.get("arquitetura", "multicamadas")

    if not isinstance(arquitetura, str) or arquitetura not in REGRAS:
        return erro("Arquitetura inválida.", 400)

    # Projeto do Módulo 1 a que a revisão pertence (usado nas notificações).
    project_id = dados.get("project_id")

    if project_id is None:
        project_id = os.getenv("NOTIFICACOES_PROJECT_ID", "").strip() or None
    elif not isinstance(project_id, str) or not 1 <= len(project_id.strip()) <= 100:
        return erro("project_id inválido.", 400)
    else:
        project_id = project_id.strip()

    try:
        pr = None

        pr_url = dados.get("pr_url")
        if pr_url is not None:
            arquivos, pr = carregar_pr(pr_url)
        else:
            arquivos = dados.get("arquivos")

        validar_arquivos(arquivos)
        relatorio = analisar(arquivos, arquitetura)

        relatorio.update({
            "id": str(uuid.uuid4()),
            "criado_em": datetime.now(timezone.utc).isoformat(),
            "arquitetura": arquitetura,
            "project_id": project_id,
            "pr": pr,
            "ia": {
                "status": "Não solicitada",
                "texto": "Esta revisão utilizou apenas análise estática.",
            },
        })

        if dados.get("usar_ia") is True:
            relatorio["ia"] = consultar_ia(arquivos, relatorio)

        relatorio["markdown"] = gerar_markdown(relatorio)
        salvar(relatorio)

        # Só avisa o Módulo 6 depois de salvar, e uma falha dele não afeta a revisão.
        relatorio["notificacao"] = notificar_revisao(relatorio)

        return JSONResponse(relatorio, status_code=201)

    except UnicodeEncodeError:
        return erro("O código ou caminho contém Unicode inválido.", 400)

    except ValueError as falha:
        return erro(str(falha), 400)

    except ErroIntegracao as falha:
        return erro(str(falha), 502)


CORPO_ANALISAR = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "pr_url": {"type": "string"},
                    "arquivos": {"type": "array", "items": {"type": "object"}},
                    "arquitetura": {"type": "string", "enum": list(REGRAS)},
                    "usar_ia": {"type": "boolean"},
                    "project_id": {"type": "string"},
                },
            },
            "example": {
                "arquivos": [{
                    "caminho": "src/controllers/exemplo.py",
                    "conteudo": "def cadastrar(dados):\n    return eval(dados)\n",
                }],
                "arquitetura": "multicamadas",
            },
        }
    },
}


@app.post("/api/analisar", openapi_extra={"requestBody": CORPO_ANALISAR})
async def revisar(request: Request):
    dados, resposta = await ler_json(request)

    if resposta:
        return resposta

    if not isinstance(dados, dict):
        return erro("Envie um objeto JSON válido.", 400)

    # A análise usa rede e banco (bloqueantes), então roda fora do loop async.
    return await run_in_threadpool(processar_analise, dados)


@app.post("/api/revisoes/{identificador}/comentar")
def comentar(identificador: str):
    relatorio = buscar(identificador)

    if not relatorio:
        return erro("Revisão não encontrada.", 404)

    if not relatorio["pr"]:
        return erro("Esta revisão não veio de um PR.", 400)

    if not os.getenv("GITHUB_TOKEN", "").strip():
        return erro("Configure GITHUB_TOKEN no .env.", 503)

    pr = relatorio["pr"]

    if acesso_aberto() and not repositorio_autorizado(pr["url"]):
        return erro(
            "Sem login, só é possível comentar nos repositórios autorizados "
            "(REPOS_COMENTARIO).",
            403,
        )

    try:
        texto = relatorio["markdown"]

        if len(texto) > 15000:
            return erro("Relatório muito grande. Exporte e publique manualmente.", 400)

        with closing(conectar()) as conexao:
            anterior = conexao.execute(
                "SELECT url FROM publicacoes WHERE revisao_id = ?",
                (identificador,),
            ).fetchone()

        if anterior:
            if anterior["url"]:
                return {"url": anterior["url"]}
            return erro("Publicação em andamento ou sem confirmação. Confira o PR.", 409)

        if obter_sha(pr) != pr["sha"]:
            return erro("O PR mudou. Faça uma nova análise antes de comentar.", 409)

        with closing(conectar()) as conexao, conexao:
            reserva = conexao.execute(
                "INSERT OR IGNORE INTO publicacoes (revisao_id) VALUES (?)",
                (identificador,),
            )
            if not reserva.rowcount:
                return erro("Publicação já solicitada. Confira o PR.", 409)

        try:
            url = publicar_revisao(pr, texto)
        except ErroIntegracao as falha:
            if falha.rejeitado:
                with closing(conectar()) as conexao, conexao:
                    conexao.execute(
                        "DELETE FROM publicacoes WHERE revisao_id = ?",
                        (identificador,),
                    )
                raise
            raise ErroIntegracao(
                "GitHub não confirmou a publicação. Confira o PR antes de tentar novamente."
            ) from falha

        with closing(conectar()) as conexao, conexao:
            conexao.execute(
                "UPDATE publicacoes SET url = ? WHERE revisao_id = ?",
                (url, identificador),
            )

        return JSONResponse({"url": url}, status_code=201)

    except ErroIntegracao as falha:
        return erro(str(falha), 502)


@app.post("/api/revisoes/{identificador}/notificar")
def renotificar(identificador: str):
    """Reenvia a notificação ao Módulo 6 (seguro: o event_id é o mesmo)."""
    relatorio = buscar(identificador)

    if not relatorio:
        return erro("Revisão não encontrada.", 404)

    notificacao = notificar_revisao(relatorio)
    codigos = {
        "enviada": 200,
        "nao_configurada": 503,
        "sem_projeto": 400,
        "falhou": 502,
    }

    return JSONResponse(
        {"notificacao": notificacao}, status_code=codigos[notificacao["status"]]
    )


def ler_parametros_metricas(request):
    """Lê project_id e dias da consulta. Retorna (project_id, dias, resposta_de_erro)."""
    consulta = request.query_params
    project_id = (consulta.get("project_id") or "").strip() or None

    try:
        dias = int(consulta.get("dias", 14))
    except ValueError:
        return None, None, erro("O parâmetro dias deve ser um número.", 400)

    if not 1 <= dias <= 90:
        return None, None, erro("O parâmetro dias deve estar entre 1 e 90.", 400)

    return project_id, dias, None


def calcular_metricas(project_id, dias):
    with closing(conectar()) as conexao, conexao:
        linhas = conexao.execute(
            "SELECT relatorio FROM revisoes ORDER BY criado_em DESC LIMIT 500"
        ).fetchall()

    revisoes = [json.loads(linha["relatorio"]) for linha in linhas]

    if project_id:
        revisoes = [r for r in revisoes if r.get("project_id") == project_id]

    por_prioridade = dict.fromkeys(PRIORIDADES, 0)
    por_categoria = {}
    por_arquitetura = {}

    hoje = datetime.now(timezone.utc).date()
    por_dia = {
        (hoje - timedelta(days=atras)).isoformat(): {"revisoes": 0, "achados": 0}
        for atras in range(dias - 1, -1, -1)
    }

    for revisao in revisoes:
        contagem = contar_por_prioridade(revisao["achados"])

        for nivel in PRIORIDADES:
            por_prioridade[nivel] += contagem[nivel]

        for item in revisao["achados"]:
            por_categoria[item["categoria"]] = por_categoria.get(item["categoria"], 0) + 1

        estilo = revisao["arquitetura"]
        por_arquitetura[estilo] = por_arquitetura.get(estilo, 0) + 1

        dia = revisao["criado_em"][:10]

        if dia in por_dia:
            por_dia[dia]["revisoes"] += 1
            por_dia[dia]["achados"] += len(revisao["achados"])

    ultimas = [
        {
            "id": r["id"],
            "criado_em": r["criado_em"],
            "project_id": r.get("project_id"),
            "arquitetura": r["arquitetura"],
            "pr": (
                {"numero": r["pr"]["numero"], "titulo": r["pr"]["titulo"], "url": r["pr"]["url"]}
                if r.get("pr")
                else None
            ),
            "total_achados": len(r["achados"]),
            "por_prioridade": contar_por_prioridade(r["achados"]),
        }
        for r in revisoes[:10]
    ]

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "total_revisoes": len(revisoes),
        "total_achados": sum(por_prioridade.values()),
        "por_prioridade": por_prioridade,
        "por_categoria": por_categoria,
        "por_arquitetura": por_arquitetura,
        "revisoes_por_dia": [{"data": dia, **valores} for dia, valores in por_dia.items()],
        "ultimas_revisoes": ultimas,
    }


@app.get("/api/metricas")
def metricas(request: Request):
    """Números prontos para gráficos do dashboard (Módulo 6). Exige a senha."""
    project_id, dias, falha = ler_parametros_metricas(request)

    if falha:
        return falha

    return calcular_metricas(project_id, dias)


@app.get("/api/dashboard/metricas")
def metricas_publicas(request: Request):
    """Mesmos números, só agregados, sem senha: alimenta a página de gráficos
    embutida no dashboard do Módulo 6. Não traz código, títulos nem links de PR."""
    project_id, dias, falha = ler_parametros_metricas(request)

    if falha:
        return falha

    dados = calcular_metricas(project_id, dias)
    dados.pop("ultimas_revisoes")

    return JSONResponse(
        dados,
        headers={
            # São só contagens: qualquer página pode ler (o dashboard do M6 inclusive).
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=30",
        },
    )


def chamar_modulo(funcao, *args):
    """Converte as falhas dos clientes de outros módulos em respostas HTTP."""
    try:
        return JSONResponse(funcao(*args))
    except ValueError as falha:
        return erro(str(falha), 400)
    except ErroIntegracao as falha:
        return erro(str(falha), 502)


@app.get("/api/modulo3/projetos")
def modulo3_projetos():
    return chamar_modulo(modulo3.listar_projetos)


@app.get("/api/modulo3/projetos/{project_id}/artefatos")
def modulo3_artefatos(project_id: str, search: str = "", tipo: str = ""):
    return chamar_modulo(
        modulo3.listar_artefatos, project_id, search or None, tipo or None
    )


@app.get("/api/modulo3/projetos/{project_id}/artefatos/{artifact_id}/versoes")
def modulo3_versoes(project_id: str, artifact_id: str):
    return chamar_modulo(modulo3.listar_versoes, project_id, artifact_id)


@app.get("/api/modulo3/analises/{analysis_id}")
def modulo3_analise(analysis_id: str):
    """Análise de IA do Módulo 3, com a arquitetura já traduzida para os nossos estilos."""
    return chamar_modulo(
        lambda: modulo3.resumir_analise(modulo3.obter_analise(analysis_id))
    )


@app.post("/api/revisoes/{identificador}/leitura-recomendada")
def leitura_recomendada(identificador: str):
    """Pede ao Módulo 5 artigos sobre os temas dos achados desta revisão."""
    relatorio = buscar(identificador)

    if not relatorio:
        return erro("Revisão não encontrada.", 404)

    pergunta = modulo5.montar_pergunta(relatorio)

    return chamar_modulo(
        lambda: {"pergunta": pergunta, "resposta": modulo5.buscar_leitura(pergunta)}
    )



# Deve ser a última rota: só atende o que nenhuma rota da API reconheceu.
@app.get("/{caminho:path}", include_in_schema=False)
def arquivos_do_frontend(caminho: str):
    if servindo_frontend():
        arquivo = arquivo_frontend(caminho)

        if arquivo:
            return FileResponse(arquivo)

    return erro("Não encontrado.", 404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5000)
