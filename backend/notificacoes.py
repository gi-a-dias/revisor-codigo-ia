"""Integração com o Módulo 6 (Dashboard e Central de Notificações).

Quando uma revisão termina, o Módulo 4 envia um evento para a central de
notificações. O envio nunca derruba a revisão: qualquer falha vira um status.
A chave de integração vem da variável de ambiente NOTIFICACOES_KEY (nunca do
código nem do GitHub).
"""
import os

import requests

URL_PADRAO = (
    "https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net"
    "/api/integrations/notifications"
)
TIMEOUT = 5

# Prioridades aceitas pelo Módulo 6, da mais para a menos urgente.
PRIORIDADES = ("critical", "high", "medium", "low")
ROTULOS = {
    "critical": "crítico(s)",
    "high": "alto(s)",
    "medium": "médio(s)",
    "low": "baixo(s)",
}


def prioridade_do_achado(item):
    """Mesma regra do front: falha de segurança grave é crítica."""
    if item["categoria"] == "Segurança" and item["gravidade"] == "Alta":
        return "critical"
    if item["gravidade"] == "Alta":
        return "high"
    if item["gravidade"] == "Média":
        return "medium"
    return "low"


def contar_por_prioridade(achados):
    contagem = dict.fromkeys(PRIORIDADES, 0)

    for item in achados:
        contagem[prioridade_do_achado(item)] += 1

    return contagem


def prioridade_da_revisao(achados):
    contagem = contar_por_prioridade(achados)

    for prioridade in PRIORIDADES:
        if contagem[prioridade]:
            return prioridade

    return "low"


def montar_notificacao(relatorio, project_id):
    contagem = contar_por_prioridade(relatorio["achados"])
    total = len(relatorio["achados"])
    pr = relatorio.get("pr")

    if pr:
        titulo = f"Code Review concluído: PR #{pr['numero']}"
    else:
        titulo = "Code Review concluído"

    if total:
        detalhes = ", ".join(
            f"{contagem[nivel]} {ROTULOS[nivel]}"
            for nivel in PRIORIDADES
            if contagem[nivel]
        )
        corpo = f"{total} achado(s): {detalhes}."
    else:
        corpo = "Nenhum achado pelas regras aplicadas."

    corpo += f" Arquitetura verificada: {relatorio['arquitetura']}."

    if pr:
        corpo += f" PR: {pr['titulo']}"

    return {
        "event_id": f"modulo4-review-{relatorio['id']}",
        "scope": "project",
        "project_id": project_id,
        "source": "code_review",
        "type": "review.completed",
        "title": titulo[:120],
        "body": corpo[:500],
        "priority": prioridade_da_revisao(relatorio["achados"]),
        "link": pr["url"] if pr else None,
    }


def enviar_notificacao(payload):
    """Envia o evento e devolve {'status', 'event_id', 'detalhe'}."""
    resultado = {"event_id": payload["event_id"], "detalhe": ""}
    chave = os.getenv("NOTIFICACOES_KEY", "").strip()

    if not chave:
        return {**resultado, "status": "nao_configurada"}

    url = os.getenv("NOTIFICACOES_URL", "").strip() or URL_PADRAO

    try:
        resposta = requests.post(
            url,
            json=payload,
            headers={"X-Integration-Key": chave, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return {
            **resultado,
            "status": "falhou",
            "detalhe": "Módulo 6 indisponível no momento.",
        }

    if resposta.status_code == 200:
        return {**resultado, "status": "enviada"}

    if resposta.status_code == 401:
        detalhe = "Chave de integração recusada pelo Módulo 6."
    elif resposta.status_code == 422:
        detalhe = "O Módulo 6 recusou os dados. Confira se o project_id existe."
    else:
        detalhe = f"O Módulo 6 respondeu HTTP {resposta.status_code}."

    return {**resultado, "status": "falhou", "detalhe": detalhe}


def notificar_revisao(relatorio):
    """Monta e envia a notificação de uma revisão já salva."""
    project_id = relatorio.get("project_id")

    if not os.getenv("NOTIFICACOES_KEY", "").strip():
        return {"status": "nao_configurada", "event_id": None, "detalhe": ""}

    if not project_id:
        # Aviso de projeto exige um project_id real do Módulo 1.
        return {
            "status": "sem_projeto",
            "event_id": None,
            "detalhe": "Informe o project_id para notificar o Módulo 6.",
        }

    return enviar_notificacao(montar_notificacao(relatorio, project_id))
