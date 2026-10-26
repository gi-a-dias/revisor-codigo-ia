import os
from pathlib import Path

import requests
from dotenv import load_dotenv

pasta = Path(__file__).resolve().parent
load_dotenv(pasta / ".env")

chave = (os.getenv("GEMINI_API_KEY") or "").strip()
modelo = (os.getenv("GEMINI_MODEL") or "").strip()

if not chave or not modelo:
    raise SystemExit("Preencha a chave e o modelo em mvp/.env.")

print("Modelo usado:", modelo)
print("Testando a Interactions API...")

try:
    resposta = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        headers={"x-goog-api-key": chave},
        json={
            "model": modelo,
            "input": "Responda somente com a palavra OK.",
            "store": False,
        },
        timeout=(5, 45),
    )

    print("Código HTTP:", resposta.status_code)

    try:
        dados = resposta.json()
    except ValueError:
        raise SystemExit("O serviço retornou uma resposta que não é JSON.")

    if not resposta.ok:
        erro = dados.get("error", {})
        mensagem = str(
            erro.get("message", "Sem detalhes disponíveis.")
        ).replace(chave, "[CHAVE OCULTA]")

        print("Status do erro:", erro.get("status", "Não informado"))
        print("Detalhe:", mensagem)

    else:
        print("Status da interação:", dados.get("status"))

        textos = []

        for etapa in dados.get("steps", []):
            if etapa.get("type") == "model_output":
                for parte in etapa.get("content", []):
                    if parte.get("type") == "text":
                        textos.append(parte.get("text", ""))

        print("Resposta:", "\n".join(textos) or "(sem texto)")

except requests.Timeout:
    print("Erro: o Google demorou demais para responder.")

except requests.RequestException as erro:
    print("Erro de conexão:", type(erro).__name__)