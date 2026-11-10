import base64
import binascii
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from analisador import REGRAS, analisar
from gemini import consultar_ia
from github_pr import ErroIntegracao, carregar_pr, obter_sha, publicar_revisao


PASTA = Path(__file__).resolve().parent
load_dotenv(PASTA / ".env")

LIMITE_CORPO = 500_000

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


@app.middleware("http")
async def verificar_acesso(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/api/health":
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
    if request.method == "POST":
        origem = request.headers.get("origin")

        if (
            origem
            and origem.rstrip("/") not in ORIGENS_PERMITIDAS
            and origem.rstrip("/") != str(request.base_url).rstrip("/")
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

        return JSONResponse(relatorio, status_code=201)

    except UnicodeEncodeError:
        return erro("O código ou caminho contém Unicode inválido.", 400)

    except ValueError as falha:
        return erro(str(falha), 400)

    except ErroIntegracao as falha:
        return erro(str(falha), 502)


@app.post("/api/analisar")
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5000)
