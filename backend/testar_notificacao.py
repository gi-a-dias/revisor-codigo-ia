"""Envia uma notificação de teste ao Módulo 6.

Uso (a partir da raiz do repositório):
    python backend/testar_notificacao.py ID_REAL_DO_PROJETO

Precisa de NOTIFICACOES_KEY no backend/.env. Informe o event_id impresso ao
responsável pelo Módulo 6 para ele conferir o recebimento.
"""
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from notificacoes import enviar_notificacao

load_dotenv(Path(__file__).resolve().parent / ".env")


def main():
    if len(sys.argv) != 2:
        print("Uso: python backend/testar_notificacao.py ID_REAL_DO_PROJETO")
        return 1

    payload = {
        "event_id": f"modulo4-teste-{int(time.time())}",
        "scope": "project",
        "project_id": sys.argv[1].strip(),
        "source": "code_review",
        "type": "review.completed",
        "title": "Teste de integração do Code Review",
        "body": "Notificação de teste enviada pelo Módulo 4.",
        "priority": "low",
        "link": None,
    }

    resultado = enviar_notificacao(payload)
    print("event_id:", resultado["event_id"])
    print("status:  ", resultado["status"])

    if resultado["detalhe"]:
        print("detalhe: ", resultado["detalhe"])

    return 0 if resultado["status"] == "enviada" else 1


if __name__ == "__main__":
    raise SystemExit(main())
