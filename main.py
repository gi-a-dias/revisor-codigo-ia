from fastapi import FastAPI

app = FastAPI(title="Módulo 4 - Revisor de Código")
@app.get("/")
def home():
    return {"status": "online", "mensagem": "API do Módulo 4 rodando!"}
