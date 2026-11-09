import pytest
from fastapi.testclient import TestClient

from tests import modelo_ficticio


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "aviso-ficticio.docx").write_bytes(modelo_ficticio.aviso_com_capa())
    from routers import minutas
    monkeypatch.setattr(minutas, "MODELOS_DIR", tmp_path)
    from main import app
    return TestClient(app)


DADOS = {"processo": "0000001-11.2026.4.01.8006", "numero": "1/2026", "objeto": "serviço fictício de teste",
         "valor_total": "1.000,00", "data_sessao": "10/12/2026", "criterio": "menor preço global", "inciso": "II",
         "signatario": "SERVIDOR FICTÍCIO", "cargo": "Supervisor de Seção"}


def test_config_lista_modelos_e_dados_fixos(client):
    r = client.get("/minutas/config").json()
    assert r["dados_jf"]["uasg"] == "090022"
    assert [m["id"] for m in r["modelos"]] == ["aviso-ficticio"]
    assert r["modelos"][0]["tipo"] == "aviso_dispensa" and r["modelos"][0]["versao"] == "MAR/2026"


def test_montar_com_formulario(client):
    r = client.post("/minutas/montar", json={"modelo_id": "aviso-ficticio", "dados": DADOS}).json()
    assert r["resumo"]["pendencias"] == 0
    assert any(b["texto"] == "AVISO DE CONTRATAÇÃO DIRETA Nº 1/2026" for b in r["blocos"])
    html = r["html_sei"]
    assert "Times New Roman" in html and "1.1.&nbsp;&nbsp;O objeto é a contratação de serviço fictício de teste." in html
    assert "#ffff00" not in html                              # nada pendente, nada em amarelo


def test_pendencias_vao_em_amarelo_e_decisoes_invalidas_sao_ignoradas(client):
    r = client.post("/minutas/montar", json={
        "modelo_id": "aviso-ficticio", "dados": {},
        "decisoes": {"remover": {"B999": "não existe"}, "campos": {"B999.1": "x"}}}).json()
    assert r["resumo"]["pendencias"] > 0
    assert "#ffff00" in r["html_sei"]
    assert not any(x["id"] == "B999" for x in r["removidos"])


def test_decisao_do_servidor_remove_e_reescreve(client):
    estrutura = client.get("/minutas/modelos/aviso-ficticio/estrutura").json()
    objeto = next(b for b in estrutura["blocos"] if b["texto"].startswith("O objeto é"))
    validade = next(b for b in estrutura["blocos"] if b["texto"].startswith("O prazo de validade"))
    r = client.post("/minutas/montar", json={"modelo_id": "aviso-ficticio", "dados": DADOS, "decisoes": {
        "remover": {validade["id"]: "Prazo tratado no TR"},
        "textos": {objeto["id"]: "O objeto é outro texto."}, "origem": {objeto["id"]: "servidor"}}}).json()
    assert any(x["id"] == validade["id"] and x["motivo"] == "Prazo tratado no TR" for x in r["removidos"])
    bloco = next(b for b in r["blocos"] if b["id"] == objeto["id"])
    assert bloco["texto"] == "O objeto é outro texto." and bloco["origem"] == "servidor"


def test_modelo_inexistente_e_upload_invalido(client):
    assert client.post("/minutas/montar", json={"modelo_id": "nao-existe"}).status_code == 404
    r = client.post("/minutas/modelos", files={"arquivo": ("x.docx", b"nao e docx", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_de_nova_versao(client):
    r = client.post("/minutas/modelos", files={"arquivo": ("novo.docx", modelo_ficticio.aviso_com_capa(), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["id"] == "aviso-dispensa-agu-MAR-2026"
    assert len(client.get("/minutas/config").json()["modelos"]) == 2
