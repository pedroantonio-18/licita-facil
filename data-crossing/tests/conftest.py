import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Cliente HTTP com banco SQLite isolado por teste."""
    monkeypatch.setenv("DATA_CROSSING_DB", str(tmp_path / "teste.db"))
    from main import app
    return TestClient(app)


def importar(client, processo_id, empresa):
    r = client.post("/conluio/importar", json={"processo_id": processo_id, **empresa})
    assert r.status_code == 200, r.text
    return r.json()


def empresa_minima(nome, cnpj, cpfs=(), pessoas=()):
    return {
        "empresa_nome": nome,
        "empresa_cnpj": cnpj,
        "cnpjs": [{"valor": cnpj, "valor_formatado": cnpj}],
        "cpfs": [{"valor": c, "valor_formatado": c} for c in cpfs],
        "ceps": [],
        "telefones": [],
        "pessoas": list(pessoas),
    }
