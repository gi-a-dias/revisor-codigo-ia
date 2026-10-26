import os
from pathlib import Path

import requests
from dotenv import load_dotenv

pasta = Path(__file__).resolve().parent
load_dotenv(pasta / ".env")

chave = os.getenv("GEMINI_API_KEY")

if not chave:
    raise SystemExit(
        "Preencha GEMINI_API_KEY no arquivo .env dentro da pasta mvp."
    )

parametros = {}

try:
    while True:
        resposta = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": chave},
            params=parametros,
            timeout=15,
        )

        if not resposta.ok:
            raise SystemExit(
                f"Não foi possível listar os modelos: "
                f"HTTP {resposta.status_code}. Confira sua chave."
            )

        dados = resposta.json()

        for modelo in dados.get("models", []):
            metodos = modelo.get("supportedGenerationMethods", [])

            if "generateContent" in metodos:
                nome = modelo["name"].removeprefix("models/")
                print(nome)

        proxima_pagina = dados.get("nextPageToken")

        if not proxima_pagina:
            break

        parametros["pageToken"] = proxima_pagina

except requests.RequestException:
    print("Não foi possível conectar ao Gemini. Tente novamente.")