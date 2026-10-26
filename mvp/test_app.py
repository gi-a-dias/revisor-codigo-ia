import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health_check(client):
    """Testa se a API está online e retornando o status correto."""
    resposta = client.get("/api/health")
    
    assert resposta.status_code == 200
    assert resposta.json == {"status": "ok", "modulo": 4}