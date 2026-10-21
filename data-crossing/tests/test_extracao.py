import fitz

from app.extraction import extractor
from tests.conftest import importar

TEXTO_SICAF = (
    "FULANO CONSULTOR DE TAL 111.444.777-35 - Governo (Uasg: 90022)\n"
    "Responsável legal: BELTRANO DE SOUZA LIMA, CPF 529.982.247-25, telefone (62) 3000-4455, "
    "CEP 74.000-100, CNPJ 11.222.333/0001-81."
)


def test_sem_llm_gera_aviso_em_vez_de_silencio(monkeypatch):
    monkeypatch.setattr(extractor, "_LLM_DISPONIVEL", None)
    monkeypatch.setattr(extractor.importlib.util, "find_spec", lambda nome: None)
    resultado = extractor.extrair([(1, TEXTO_SICAF)])
    assert resultado.pessoas == []
    assert resultado.avisos == [extractor.AVISO_LLM_INDISPONIVEL]


def test_cpf_do_consultante_sicaf_e_desconsiderado_na_extracao():
    resultado = extractor.extrair([(3, TEXTO_SICAF)], usar_llm=False)
    assert [c.valor for c in resultado.cpfs] == ["52998224725"]
    assert resultado.desconsiderados[0]["valor"] == "11144477735"
    assert resultado.telefones[0].pagina == 3
    assert [c.valor for c in resultado.ceps] == ["74000100"]


def _pdf(texto):
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), texto, fontsize=9)
    return doc.tobytes()


def test_processar_pdf_local_e_cruzar(client):
    """Caminho sem chave do Gemini: extração local + cruzamento + relatório."""
    texto_a = "CONTRATO SOCIAL\nSocio: CPF 529.982.247-25\nCNPJ 11.222.333/0001-81\n" + "x" * 60
    texto_b = "ALTERACAO CONTRATUAL\nProcurador CPF 529.982.247-25\nCNPJ 11.444.777/0001-61\n" + "y" * 60
    for nome, cnpj, texto in (("ALFA LTDA", "11222333000181", texto_a), ("BETA LTDA", "11444777000161", texto_b)):
        r = client.post(
            "/conluio/processar",
            data={"processo_id": "local", "empresa_nome": nome, "empresa_cnpj": cnpj},
            files={"arquivos": (f"{nome}.pdf", _pdf(texto), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["cpfs_encontrados"] == 1

    achados = client.post("/conluio/cruzar/local").json()["achados"]
    assert [(a["id"], a["regra_codigo"]) for a in achados] == [("A001", "R02")]
    assert achados[0]["evidencia_a"]["pagina"] == 1
    assert client.get("/conluio/relatorio/local").status_code == 200


def test_identificar_sugere_cnpj_e_razao_social(client):
    texto = (
        "ALTERACAO CONTRATUAL DA ALFA COMERCIO DE VEICULOS LTDA, inscrita no CNPJ 11.222.333/0001-81\n"
        "Assinatura validada 02088698000174 (JUCEG) 02088698000174 02088698000174\n"
        "ALFA COMERCIO DE VEICULOS LTDA - CNPJ 11.222.333/0001-81 - sede em Goiania\n"
    )
    r = client.post("/conluio/identificar", files={"arquivos": ("a.pdf", _pdf(texto), "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["cnpj"] == "11222333000181"            # JUCEG é mais frequente, mas é ignorada
    assert r.json()["razao_social"] == "ALFA COMERCIO DE VEICULOS LTDA"


def test_identificar_sem_cnpj(client):
    r = client.post("/conluio/identificar", files={"arquivos": ("a.pdf", _pdf("sem dados " * 20), "application/pdf")})
    assert r.json() == {"cnpj": None, "cnpj_formatado": None, "razao_social": None, "ocorrencias_cnpj": 0}
