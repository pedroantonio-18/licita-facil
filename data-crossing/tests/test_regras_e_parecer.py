import fitz
import pytest

from app.crossing.parecer import validar_parecer, linguagem_conclusiva
from tests.conftest import importar, empresa_minima

PROCESSO = "proc-teste"

ALFA = "11222333000181"
BETA = "11444777000161"
CPF_COMUM = "52998224725"


def _cruzar_par(client, pessoas_a=(), pessoas_b=(), cpfs=(CPF_COMUM,)):
    importar(client, PROCESSO, empresa_minima("ALFA LTDA", ALFA, cpfs=cpfs, pessoas=pessoas_a))
    importar(client, PROCESSO, empresa_minima("BETA LTDA", BETA, cpfs=cpfs, pessoas=pessoas_b))
    r = client.post(f"/conluio/cruzar/{PROCESSO}")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------

def test_cpf_comum_gera_r02_com_id_e_prioridade(client):
    achados = _cruzar_par(client)["achados"]
    assert len(achados) == 1
    assert achados[0]["id"] == "A001"
    assert achados[0]["regra_codigo"] == "R02"
    assert achados[0]["prioridade"] == "alta"
    assert achados[0]["valor"] == "529.982.247-25"   # exibido sempre formatado


def test_cpf_ignorado_por_variavel_de_ambiente(client, monkeypatch):
    monkeypatch.setenv("CPF_IGNORADOS", "529.982.247-25")
    resultado = _cruzar_par(client)
    assert resultado["total_achados"] == 0
    assert resultado["desconsiderados"][0]["motivo"] == "Usuário consultante no cabeçalho das consultas SICAF"


def test_r06_exige_funcao_identificada(client):
    """Duas pessoas homônimas sem função conhecida não são 'mesma função'."""
    pessoa = {"nome": "FULANO DE TAL SOUZA"}
    regras = {a["regra_codigo"] for a in _cruzar_par(client, [pessoa], [pessoa], cpfs=())["achados"]}
    assert regras == {"R05"}


def test_r06_mesma_pessoa_mesma_funcao(client):
    pessoa = {"nome": "FULANO DE TAL SOUZA", "funcao": "Procurador"}
    achados = _cruzar_par(client, [pessoa], [{**pessoa, "funcao": "procurador"}], cpfs=())["achados"]
    assert [(a["id"], a["regra_codigo"]) for a in achados] == [("A001", "R05"), ("A002", "R06")]


def test_reimportar_empresa_substitui_em_vez_de_duplicar(client):
    _cruzar_par(client)
    importar(client, PROCESSO, empresa_minima("ALFA LTDA", ALFA))  # sem o CPF agora
    sessao = client.get(f"/conluio/sessao/{PROCESSO}").json()
    assert len(sessao["empresas"]) == 2
    assert "achados" not in sessao  # dados mudaram: cruzamento anterior invalidado
    assert client.post(f"/conluio/cruzar/{PROCESSO}").json()["total_achados"] == 0


def test_sessao_persiste_entre_instancias(client, tmp_path):
    _cruzar_par(client)
    from fastapi.testclient import TestClient
    from main import app
    novo = TestClient(app)
    assert novo.get(f"/conluio/sessao/{PROCESSO}").json()["achados"][0]["id"] == "A001"


# ---------------------------------------------------------------------------
# Parecer — validação
# ---------------------------------------------------------------------------

IDS = {"A001", "A002"}


def test_item_valido_e_aceito():
    p = validar_parecer({"itens": [{"texto": "Coincidência de CPF a verificar; recomenda-se consultar o QSA.", "achados": ["A001"]}]}, IDS)
    assert len(p["aceitos"]) == 1 and not p["descartados"]


def test_item_sem_citacao_e_descartado():
    p = validar_parecer({"itens": [{"texto": "As empresas parecem próximas.", "achados": []}]}, IDS)
    assert p["descartados"][0]["motivo"] == "não cita nenhum achado ou dado"


def test_item_com_achado_inexistente_e_descartado():
    p = validar_parecer({"itens": [{"texto": "Ver A001 e A009.", "achados": ["A001"]}]}, IDS)
    assert p["descartados"][0]["motivo"] == "cita referência inexistente: A009"


@pytest.mark.parametrize("texto", [
    "Houve conluio entre as empresas.",
    "Ficou comprovado o vínculo societário.",
    "O achado comprova a combinação de preços.",
    "Há indícios de fraude na licitação.",
    "As empresas estão em conluio.",
    "Certamente trata-se do mesmo grupo.",
    "Sem dúvida há relação entre as licitantes.",
    "A IA identificou o esquema.",
    "Conduta ilícita das licitantes.",
    "Não houve conluio entre as licitantes.",
    "Não há conluio entre as empresas.",
    "O conluio está descartado.",
    "Ficou afastada a hipótese de combinação.",
])
def test_linguagem_conclusiva_e_descartada(texto):
    p = validar_parecer({"itens": [{"texto": texto, "achados": ["A001"]}]}, IDS)
    assert not p["aceitos"], texto
    assert p["descartados"][0]["motivo"].startswith("linguagem conclusiva")


@pytest.mark.parametrize("texto", [
    "Coincidência que pode ter explicação lícita; recomenda-se diligência.",
    "Indício a verificar: solicitar comprovante de endereço.",
    "Recomenda-se verificar se há procuração que comprove a representação.".replace("comprove", "demonstre"),
    "Não foram identificados indícios de conluio nos dados analisados.",
    "Não há indícios de vínculo entre as licitantes nos documentos apresentados.",
])
def test_linguagem_nao_conclusiva_passa(texto):
    assert linguagem_conclusiva(texto) is None


def test_resposta_invalida_vira_descarte_registrado():
    p = validar_parecer("não sei responder", IDS)
    assert not p["aceitos"]
    assert p["descartados"][0]["motivo"].startswith("resposta inválida")


def test_resposta_em_texto_com_markdown():
    bruto = '```json\n{"itens": [{"texto": "Coincidência a verificar.", "achados": ["A002"]}]}\n```'
    assert len(validar_parecer(bruto, IDS)["aceitos"]) == 1


# ---------------------------------------------------------------------------
# Parecer — fluxo HTTP e relatório
# ---------------------------------------------------------------------------

def test_fluxo_parecer_no_relatorio(client):
    _cruzar_par(client)

    prompt = client.get(f"/conluio/parecer/{PROCESSO}/prompt").json()
    assert prompt["aplicavel"] and prompt["ids"][:3] == ["A001", "E1", "E2"]
    assert "A001" in prompt["prompt"]
    assert prompt["prompt"].count("529.982.247-25") == 1   # CPF só no valor do achado, não no catálogo
    assert "52998224725" not in prompt["prompt"]

    resposta = {"itens": [
        {"texto": "O mesmo CPF consta nas duas empresas; recomenda-se verificar a função exercida.", "achados": ["A001"]},
        {"texto": "Houve conluio evidente.", "achados": ["A001"]},
        {"texto": "Ver também o achado A007.", "achados": ["A007"]},
    ]}
    r = client.post(f"/conluio/parecer/{PROCESSO}", json={"modelo": "gemini-teste", "resposta": resposta})
    assert r.status_code == 200, r.text
    parecer = r.json()
    assert len(parecer["aceitos"]) == 1 and len(parecer["descartados"]) == 2

    pdf = client.get(f"/conluio/relatorio/{PROCESSO}").content
    texto = "".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))
    assert "Parecer preliminar gerado por inteligência artificial" in texto
    assert "recomenda-se verificar a função exercida" in texto
    assert "Itens descartados pela validação automática (2)" in texto
    assert "cita referência inexistente: A007" in texto
    assert "Não há avaliação geral" in texto
    assert client.get(f"/conluio/relatorios/{PROCESSO}").json()["relatorios"][0]["com_parecer"] is True


def test_novo_cruzamento_descarta_parecer_anterior(client):
    _cruzar_par(client)
    client.post(f"/conluio/parecer/{PROCESSO}", json={"resposta": {"itens": []}})
    client.post(f"/conluio/cruzar/{PROCESSO}")
    assert "parecer" not in client.get(f"/conluio/sessao/{PROCESSO}").json()


# ---------------------------------------------------------------------------
# Parecer — avaliação geral
# ---------------------------------------------------------------------------

def _avaliacao(nivel, fundamentacao, referencias=()):
    return {"avaliacao_geral": {"nivel": nivel, "fundamentacao": fundamentacao, "referencias": list(referencias)}, "itens": []}


def test_avaliacao_sem_indicios_sem_achados(client):
    """Caso das 6 empresas: sem achados, o parecer ainda dá a avaliação geral."""
    _cruzar_par(client, cpfs=())
    r = client.post(f"/conluio/parecer/{PROCESSO}", json={"modelo": "gemini-teste", "resposta": _avaliacao(
        "sem_indicios",
        "As empresas E1 e E2 não compartilham sócios, procuradores, telefones ou endereços nos dados analisados; "
        "não foram identificados indícios de conluio.",
        ["E1", "E2"],
    )})
    assert r.status_code == 200, r.text
    avaliacao = r.json()["avaliacao_geral"]
    assert avaliacao["nivel"] == "sem_indicios"
    assert avaliacao["conclusao"].startswith("Na avaliação preliminar do modelo, os dados analisados não apresentam")

    pdf = client.get(f"/conluio/relatorio/{PROCESSO}").content
    texto = " ".join(" ".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf")).split())
    assert "4.1. Avaliação geral" in texto
    assert "não apresentam indícios de conluio" in texto
    assert "não exclui a existência de vínculos não documentados" in texto


def test_avaliacao_sem_indicios_precisa_examinar_achados_de_prioridade_alta():
    p = validar_parecer(_avaliacao("sem_indicios", "Nada relevante entre E1 e E2.", ["E1"]),
                        {"A001", "E1", "E2"}, ids_alta={"A001"})
    assert p["avaliacao_geral"] is None
    assert "sem examinar achado(s) de prioridade alta: A001" in p["descartados"][0]["motivo"]

    p = validar_parecer(_avaliacao("sem_indicios", "O CPF de A001 é do contador comum às duas; recomenda-se confirmar.", ["A001"]),
                        {"A001", "E1"}, ids_alta={"A001"})
    assert p["avaliacao_geral"]["nivel"] == "sem_indicios"


@pytest.mark.parametrize("nivel,fundamentacao,referencias,motivo", [
    ("talvez", "Coincidência em A001.", ["A001"], "nível de avaliação fora da escala"),
    ("indicios_relevantes", "Há sinais fortes.", [], "nível com indícios sem citar achados ou dados"),
    ("coincidencias_a_verificar", "Ver E9.P1.", ["E9.P1"], "cita referência inexistente: E9.P1"),
    ("sem_indicios", "Não houve conluio entre E1 e E2.", ["E1"], "linguagem conclusiva"),
])
def test_avaliacao_invalida_e_descartada(nivel, fundamentacao, referencias, motivo):
    p = validar_parecer(_avaliacao(nivel, fundamentacao, referencias), {"A001", "E1", "E2"})
    assert p["avaliacao_geral"] is None
    assert p["descartados"][0]["motivo"].startswith(motivo)


def test_catalogo_numera_empresas_e_pessoas(client):
    pessoa = {"nome": "FULANO DE TAL", "cpf": "529.982.247-25", "funcao": "procurador", "conjuge": "BELTRANA"}
    _cruzar_par(client, [pessoa], [], cpfs=())
    from app.crossing.parecer import montar_catalogo
    catalogo = montar_catalogo(client.get(f"/conluio/sessao/{PROCESSO}").json())
    assert catalogo["E1"].startswith("Empresa licitante: ALFA LTDA")
    assert catalogo["E1.P1"] == "FULANO DE TAL; função: procurador; cônjuge: BELTRANA"
    assert "529" not in catalogo["E1.P1"]


def test_importar_registra_modelo_usado(client):
    importar(client, PROCESSO, {**empresa_minima("ALFA LTDA", ALFA), "modelo": "gemini-3.8-flash"})
    empresa = client.get(f"/conluio/sessao/{PROCESSO}").json()["empresas"][0]
    assert empresa["origem"] == "Gemini gemini-3.8-flash (via navegador)"


def test_importar_descarta_cnpj_e_cpf_com_digito_invalido(client):
    empresa = empresa_minima("ALFA LTDA", ALFA, cpfs=("52998224726",))          # último dígito errado
    empresa["cnpjs"].append({"valor": "45871236000199", "valor_formatado": "45.871.236/0001-99"})
    empresa["pessoas"] = [{"nome": "FULANO DE TAL", "cpf": "111.222.333-00"}]  # inválido
    r = importar(client, PROCESSO, empresa)
    assert r["cpfs_importados"] == 0 and r["cnpjs_importados"] == 1 and r["invalidos_descartados"] == 3

    importar(client, PROCESSO, empresa_minima("BETA LTDA", BETA))
    resultado = client.post(f"/conluio/cruzar/{PROCESSO}").json()
    motivos = {d["valor"]: d["motivo"] for d in resultado["desconsiderados"]}
    assert "45.871.236/0001-99" in motivos
    assert motivos["111.222.333-00 (FULANO DE TAL)"].startswith("Dígito verificador inválido")


def test_importar_usa_a_forma_valida_quando_gemini_diverge(client):
    """Caso visto em produção: dígitos errados em "valor", forma formatada correta."""
    empresa = empresa_minima("ALFA LTDA", ALFA)
    empresa["cnpjs"].append({"valor": "45871236000113", "valor_formatado": "45.871.236/0001-31"})
    empresa["ceps"] = [{"valor": "5803000", "valor_formatado": "58030-00"}]   # CEP truncado
    r = importar(client, PROCESSO, empresa)
    assert r["cnpjs_importados"] == 2 and r["invalidos_descartados"] == 1

    sessao = client.get(f"/conluio/sessao/{PROCESSO}").json()
    fca = sessao["empresas"][0]["cnpjs"][1]
    assert (fca["valor"], fca["valor_formatado"]) == ("45871236000131", "45.871.236/0001-31")
    assert sessao["empresas"][0]["desconsiderados_extracao"][0]["tipo"] == "cep"


def test_cpf_so_na_qualificacao_da_pessoa_entra_no_cruzamento(client):
    """Gemini pode trazer o CPF apenas dentro de 'pessoas'; a R02 precisa enxergá-lo."""
    pessoa_a = {"nome": "CLARA MENDES", "cpf": "529.982.247-25", "funcao": "sócia"}
    pessoa_b = {"nome": "MARIA DE SOUZA", "cpf": "529.982.247-25", "funcao": "procuradora"}
    achados = _cruzar_par(client, [pessoa_a], [pessoa_b], cpfs=())["achados"]
    assert [a["regra_codigo"] for a in achados] == ["R02"]
