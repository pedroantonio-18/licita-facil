from fastapi.testclient import TestClient

from main import app

c = TestClient(app)


def test_config():
    r = c.get("/enquadramento/config").json()
    assert r["limites"]["2026"]["II"] == "65.492,11" and "bem" in r["naturezas"]


def test_gerar_dispensa_e_pregao():
    base = {"natureza": "bem", "exercicio": "2026", "dados": {"objeto": "aquisição fictícia", "doc_referencia": "DFD (1)",
                                                             "relatorio": "2", "metodologia": "inexistente"}}
    r = c.post("/enquadramento/gerar", json={**base, "itens": [{"descricao": "x", "valor": "18.000,00"}]}).json()
    assert r["enquadramento"]["modalidade"] == "dispensa" and r["enquadramento"]["seguridade"] == "3.600,00"
    assert r["pendencias"] == 0 and "Times New Roman" in r["html_sei"]
    r = c.post("/enquadramento/gerar", json={**base, "itens": [{"valor": "100.000,00"}]}).json()
    assert r["enquadramento"]["modalidade"] == "pregao" and r["pendencias"] == 1      # falta ref. ao bem comum


def test_erros():
    assert c.post("/enquadramento/gerar", json={"natureza": "bem", "exercicio": "2026", "itens": [{"valor": "abc"}]}).status_code == 400
    assert c.post("/enquadramento/gerar", json={"natureza": "bem", "exercicio": "2026", "itens": []}).status_code == 400
    assert c.post("/enquadramento/gerar", json={"natureza": "xyz", "exercicio": "2026", "itens": [{"valor": "1"}]}).status_code == 400
