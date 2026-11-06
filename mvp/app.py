import hmac
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from analisador import REGRAS, analisar
from gemini import consultar_ia
from github_pr import ErroIntegracao, carregar_pr, obter_sha, publicar_revisao


PASTA = Path(__file__).resolve().parent
load_dotenv(PASTA / ".env")

app = Flask(__name__)
if os.getenv("WEBSITE_HOSTNAME"):
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=0,
        x_proto=1,
    )
app.config["MAX_CONTENT_LENGTH"] = 500_000

BANCO = Path(
    os.getenv("DATABASE_PATH") or str(PASTA / "revisoes.db")
)
BANCO.parent.mkdir(parents=True, exist_ok=True)


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


@app.before_request
def verificar_acesso():
    if request.endpoint == "health":
        return

    senha = os.getenv("REVIEW_ACCESS_KEY", "").strip()
    if not senha:
        if os.getenv("GITHUB_TOKEN", "").strip():
            return jsonify({
                "erro": "Configure REVIEW_ACCESS_KEY para usar GITHUB_TOKEN."
            }), 503
        return

    credenciais = request.authorization
    if (
        credenciais
        and credenciais.type == "basic"
        and credenciais.username == "revisor"
        and hmac.compare_digest(
            (credenciais.password or "").encode("utf-8"), senha.encode("utf-8")
        )
    ):
        return

    return (
        jsonify({"erro": "Acesso restrito ao revisor."}),
        401,
        {"WWW-Authenticate": 'Basic realm="Revisor de Codigo", charset="UTF-8"'},
    )


@app.before_request
def verificar_origem():
    # Impede solicitações do navegador originadas de outro site.
    if request.method == "POST":
        origem = request.headers.get("Origin")

        if origem and origem != request.host_url.rstrip("/"):
            return jsonify({"erro": "Origem da solicitação inválida."}), 403


@app.get("/")
def inicio():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "modulo": 4})


@app.get("/api/historico")
def historico():
    with closing(conectar()) as conexao, conexao:
        linhas = conexao.execute(
            "SELECT relatorio FROM revisoes "
            "ORDER BY criado_em DESC LIMIT 20"
        ).fetchall()

    return jsonify([json.loads(linha["relatorio"]) for linha in linhas])


@app.post("/api/analisar")
def revisar():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie um objeto JSON válido."}), 400

    arquitetura = dados.get("arquitetura", "multicamadas")

    if not isinstance(arquitetura, str) or arquitetura not in REGRAS:
        return jsonify({"erro": "Arquitetura inválida."}), 400

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

        return jsonify(relatorio), 201

    except UnicodeEncodeError:
        return jsonify({"erro": "O código ou caminho contém Unicode inválido."}), 400

    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400

    except ErroIntegracao as erro:
        return jsonify({"erro": str(erro)}), 502


@app.post("/api/revisoes/<identificador>/comentar")
def comentar(identificador):
    relatorio = buscar(identificador)

    if not relatorio:
        return jsonify({"erro": "Revisão não encontrada."}), 404

    if not relatorio["pr"]:
        return jsonify({"erro": "Esta revisão não veio de um PR."}), 400

    if not os.getenv("GITHUB_TOKEN", "").strip():
        return jsonify({"erro": "Configure GITHUB_TOKEN no .env."}), 503

    pr = relatorio["pr"]

    try:
        texto = relatorio["markdown"]

        if len(texto) > 15000:
            return jsonify({
                "erro": "Relatório muito grande. Exporte e publique manualmente."
            }), 400

        with closing(conectar()) as conexao:
            anterior = conexao.execute(
                "SELECT url FROM publicacoes WHERE revisao_id = ?",
                (identificador,),
            ).fetchone()

        if anterior:
            if anterior["url"]:
                return jsonify({"url": anterior["url"]})
            return jsonify({
                "erro": "Publicação em andamento ou sem confirmação. Confira o PR."
            }), 409

        if obter_sha(pr) != pr["sha"]:
            return jsonify({
                "erro": "O PR mudou. Faça uma nova análise antes de comentar."
            }), 409

        with closing(conectar()) as conexao, conexao:
            reserva = conexao.execute(
                "INSERT OR IGNORE INTO publicacoes (revisao_id) VALUES (?)",
                (identificador,),
            )
            if not reserva.rowcount:
                return jsonify({"erro": "Publicação já solicitada. Confira o PR."}), 409

        try:
            url = publicar_revisao(pr, texto)
        except ErroIntegracao as erro:
            if erro.rejeitado:
                with closing(conectar()) as conexao, conexao:
                    conexao.execute(
                        "DELETE FROM publicacoes WHERE revisao_id = ?",
                        (identificador,),
                    )
                raise
            raise ErroIntegracao(
                "GitHub não confirmou a publicação. Confira o PR antes de tentar novamente."
            ) from erro

        with closing(conectar()) as conexao, conexao:
            conexao.execute(
                "UPDATE publicacoes SET url = ? WHERE revisao_id = ?",
                (url, identificador),
            )

        return jsonify({"url": url}), 201

    except ErroIntegracao as erro:
        return jsonify({"erro": str(erro)}), 502


@app.errorhandler(413)
def entrada_grande(erro):
    return jsonify({"erro": "Solicitação maior que o limite permitido."}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)