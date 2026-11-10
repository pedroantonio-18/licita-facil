import json

import pytest
from fastapi.testclient import TestClient

from app import pca
from app.pca import DemandaPCA, buscar, de_json

FICTICIAS = [
    DemandaPCA("SJGO_SETX_0001_2026", "NUASG/SETX", "Aquisição de água mineral, natural, sem gás, garrafa 500 ml",
               "Contratação direta - Dispensa", "Nova contratação", "3.600,00", "3.600,00", "0000001-11.2026.4.01.8006"),
    DemandaPCA("SJGO_SETX_0002_2026", "NUASG/SETX", "Limpeza do terreno para construção da sede fictícia",
               "Contratação direta - Dispensa", "Nova contratação", "10.000,00", "10.000,00", ""),
    DemandaPCA("SJGO_SETX_0003_2026", "NUASG/SETX", "Serviços continuados de vigilância armada",
               "Licitação - Pregão (sem registro de preço)", "Prorrogação (Contrato ou ARP)", "900.000,00", "900.000,00", ""),
]


def test_busca_por_palavras_chave_ignora_palavras_genericas():
    r = buscar(FICTICIAS, "aquisição de água mineral sem gás em garrafas de 500 ml")
    assert [x["id"] for x in r] == ["SJGO_SETX_0001_2026"] and r[0]["dispensa"]
    assert [x["id"] for x in buscar(FICTICIAS, "contratação de limpeza de terreno")] == ["SJGO_SETX_0002_2026"]
    assert buscar(FICTICIAS, "contratação de serviços especializados") == []     # só palavras genéricas
    assert buscar(FICTICIAS, "aquisição de desfibrilador") == []


def test_lista_em_json():
    d = de_json({"demandas": [{"id": "X_1", "descricao": "Água  mineral", "desembolso": "R$ 1.200,00"}, {"descricao": ""}]})
    assert len(d) == 1 and d[0].descricao == "Água mineral" and d[0].desembolso == "1.200,00"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pca, "PASTA", tmp_path)
    from main import app
    return TestClient(app)


def test_api_lista_colada_busca_e_pdf_sem_tabela(client):
    corpo = json.dumps({"demandas": [vars(d) for d in FICTICIAS]}, ensure_ascii=False)
    assert client.post("/enquadramento/pca/2026/lista", json={"resposta": f"Segue:\n```json\n{corpo}\n```"}).json()["demandas"] == 3
    assert client.get("/enquadramento/config").json()["pca"]["2026"]["demandas"] == 3
    r = client.post("/enquadramento/pca/2026/buscar", json={"objeto": "água mineral 500 ml"}).json()
    assert r["sugestoes"][0]["id"] == "SJGO_SETX_0001_2026"
    assert client.post("/enquadramento/pca/2027/buscar", json={"objeto": "x"}).status_code == 404
    assert client.post("/enquadramento/pca/2026/lista", json={"resposta": '{"erro": "anexo não recebido"}'}).status_code == 400
    import fitz
    doc = fitz.open(); doc.new_page().insert_text((50, 50), "PCA sem tabela legível"); pdf = doc.tobytes()
    r = client.post("/enquadramento/pca/2027", files={"arquivo": ("pca.pdf", pdf, "application/pdf")}).json()
    assert r == {"ano": "2027", "demandas": 0, "em_imagem": True}
