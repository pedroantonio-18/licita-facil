import base64
import json
from datetime import date

import fitz
import pytest
from fastapi.testclient import TestClient

from app.certidoes import NEGATIVA, PENDENTE, POSITIVA, POSITIVA_EFEITO_NEGATIVA, ler_pdf
from app.conferencia import ATENCAO, FALTANDO, OK, PROBLEMA, Parametros, conferir_certidao, montar_checklist
from tests import ficticias as f

REF = date(2026, 10, 10)


def _ler(texto, *mais):
    return ler_pdf([texto, *mais], "doc.pdf")


def _conferir(texto, cnpj="11222333000181", p=None):
    p = p or Parametros(data_referencia=REF)
    return [conferir_certidao(c, cnpj, p) for c in _ler(texto)]


# ---------------------------------------------------------------------------
# Leitura de cada tipo
# ---------------------------------------------------------------------------

def test_federal_negativa():
    (c,) = _ler(f.federal())
    assert (c.tipo, c.resultado, c.emissao, c.validade_fim) == ("federal", NEGATIVA, date(2026, 10, 5), date(2027, 4, 3))
    assert c.cnpjs == ["11222333000181"]


@pytest.mark.parametrize("tipo,esperado", [("EFEITO", POSITIVA_EFEITO_NEGATIVA), ("POSITIVA", POSITIVA)])
def test_federal_positivas(tipo, esperado):
    assert _ler(f.federal(tipo=tipo))[0].resultado == esperado


def test_fgts_validade_em_intervalo():
    (c,) = _ler(f.fgts())
    assert (c.tipo, c.resultado) == ("fgts", NEGATIVA)
    assert (c.validade_inicio, c.validade_fim, c.emissao) == (date(2026, 10, 1), date(2026, 10, 30), date(2026, 10, 5))


def test_fgts_impresso_pelo_navegador_com_ligadura():
    """Layout real do CRF salvo pela impressão do navegador: cabeçalho com data/hora e "ﬁ" ligado."""
    texto = ("20/10/2026, 21:38\nConsulta Regularidade do Empregador\nPágina 1 de 1\n"
             + f.fgts(inicio="13/10/2026", fim="11/11/2026", obtida="20/10/2026")
             .replace("Certificado de Regularidade do FGTS", "Certiﬁcado de Regularidade\ndo FGTS")
             .replace("Razão Social:", "Razão\nsocial:"))
    (c,) = _ler(texto)
    assert (c.tipo, c.resultado, c.emissao) == ("fgts", NEGATIVA, date(2026, 10, 20))
    assert (c.validade_inicio, c.validade_fim) == (date(2026, 10, 13), date(2026, 11, 11))


def test_trabalhista():
    (c,) = _ler(f.trabalhista())
    assert (c.tipo, c.resultado, c.emissao, c.validade_fim) == ("trabalhista", NEGATIVA, date(2026, 10, 5), date(2027, 4, 3))


def test_tcu_cadastros_e_data():
    (c,) = _ler(f.tcu())
    assert (c.tipo, c.resultado, c.emissao) == ("tcu", NEGATIVA, date(2026, 10, 5))
    assert len(c.detalhes) == 4 and c.detalhes[0] == "Licitantes Inidôneos: Nada Consta"


@pytest.mark.parametrize("mensagem", [
    "Sistema do CNJ está indisponível",               # PDF real de 20/10/2026
    "Dados do sistema CNJ estão indisponíveis",       # tela do site, mesmo dia
    "Erro ao consultar o cadastro",
    "Não foi possível realizar a consulta",
])
def test_tcu_sistema_indisponivel_fica_pendente(mensagem):
    (c,) = _ler(f.tcu(cnj=mensagem))
    assert c.resultado == PENDENTE


def test_falencia_data_por_extenso():
    (c,) = _ler(f.falencia())
    assert (c.tipo, c.resultado, c.emissao) == ("falencia", NEGATIVA, date(2026, 10, 5))
    assert _ler(f.falencia(consta=True))[0].resultado == POSITIVA


def test_varias_certidoes_no_mesmo_pdf():
    certidoes = ler_pdf([f.federal(), f.fgts(), f.trabalhista(), "continuação sem título", f.tcu()], "tudo.pdf")
    assert [(c.tipo, c.paginas) for c in certidoes] == [
        ("federal", [1]), ("fgts", [2]), ("trabalhista", [3, 4]), ("tcu", [5]),
    ]


def test_sicaf_com_pendencia_pede_conferencia():
    """Layout real da Consulta Nível II do SICAF (cabeçalho do consultante, data por extenso no rodapé)."""
    texto = ("FULANO CONSULTOR 111.444.777-35 - Governo (Uasg: 90022)\nConsulta Nível II – Habilitação Jurídica\n"
             f"Fornecedor\nCNPJ\n{f.ALFA[1]}\nRazão Social\n{f.ALFA[0]}\nSituação do Fornecedor\nCredenciado\n"
             "Data de Vencimento do Cadastro\n28/08/2027\nSituação do Nível II\nCadastrado - Possui pendência\n"
             "SICAF - Sistema de Cadastramento Unificado de Fornecedores\nBrasília, 05 de Outubro de 2026")
    (r,) = _conferir(texto)
    assert r.certidao.tipo == "sicaf" and r.certidao.emissao == date(2026, 10, 5)
    assert r.situacao == ATENCAO and "SICAF registra pendência" in r.observacoes[-1]


def test_documento_desconhecido():
    (c,) = _ler("Planilha de composição de custos da proposta")
    assert c.tipo == "outro"


def test_contrato_social_que_cita_falencia_e_habilitacao_juridica():
    """Caso real: cláusula com "falência" e "prefeitura" fazia o contrato virar certidão."""
    (c,) = _ler(f.contrato_social())
    assert c.tipo == "habilitacao"


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------

def test_certidao_valida_ok():
    assert _conferir(f.federal())[0].situacao == OK


def test_certidao_vencida():
    (r,) = _conferir(f.federal(valida_ate="01/10/2026"))
    assert r.situacao == PROBLEMA and r.observacoes[0].startswith("Vencida em 01/10/2026")


def test_certidao_positiva_e_problema():
    assert _conferir(f.federal(tipo="POSITIVA"))[0].situacao == PROBLEMA


def test_positiva_com_efeito_de_negativa_e_ok():
    assert _conferir(f.federal(tipo="EFEITO"))[0].situacao == OK


def test_cnpj_de_outra_empresa():
    (r,) = _conferir(f.federal(empresa=f.BETA))
    assert r.situacao == PROBLEMA and "não é desta empresa" in r.observacoes[0]


def test_filial_vale_para_federal_mas_nao_para_fgts():
    filial = "11222333000262"
    assert _conferir(f.federal(), cnpj=filial)[0].situacao == OK          # federal abrange matriz e filiais
    (r,) = _conferir(f.fgts(), cnpj=filial)                               # CRF é por estabelecimento
    assert r.situacao == ATENCAO and "outro estabelecimento" in r.observacoes[0]


def test_tcu_vale_por_dias_parametrizados():
    p = Parametros(data_referencia=REF, dias_consultas=3)
    (r,) = _conferir(f.tcu(data="05/10/2026"), p=p)
    assert r.situacao == PROBLEMA and r.certidao.validade_origem == "3 dias da emissão (parâmetro)"
    assert _conferir(f.tcu(data="05/10/2026"), p=Parametros(data_referencia=REF, dias_consultas=30))[0].situacao == OK


def test_tcu_pendente_e_atencao():
    assert _conferir(f.tcu(cnj="Sistema do CNJ está indisponível"))[0].situacao == ATENCAO


def test_checklist_aponta_obrigatoria_faltando():
    p = Parametros(data_referencia=REF)
    conferencias = [conferir_certidao(c, "11222333000181", p) for c in _ler(f.federal(), f.fgts())]
    itens = {i.tipo: i for i in montar_checklist(conferencias, p)}
    assert itens["federal"].situacao == OK and itens["fgts"].situacao == OK
    assert itens["trabalhista"].situacao == FALTANDO and itens["tcu"].situacao == FALTANDO


def test_checklist_com_duas_do_mesmo_tipo_usa_a_melhor():
    p = Parametros(data_referencia=REF)
    vencida = _ler(f.federal(valida_ate="01/10/2026"))[0]
    valida = _ler(f.federal())[0]
    itens = montar_checklist([conferir_certidao(c, "11222333000181", p) for c in (vencida, valida)], p)
    federal = next(i for i in itens if i.tipo == "federal")
    assert federal.situacao == OK and "2 documentos deste tipo" in federal.observacoes[-1]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNTADA_DIR", str(tmp_path / "sessoes"))
    from main import app
    return TestClient(app)


def _enviar(client, empresa, arquivos, sessao_id=None, **extra):
    data = {"processo_id": "0001234-55.2026.4.01.3500", "data_referencia": "2026-10-10",
            "empresa_nome": empresa[0], "empresa_cnpj": empresa[1], **extra}
    if sessao_id:
        data["sessao_id"] = sessao_id
    files = [("arquivos", (nome, conteudo, "application/pdf")) for nome, conteudo in arquivos]
    r = client.post("/juntada/conferir", data=data, files=files)
    assert r.status_code == 200, r.text
    return r.json()


KIT_COMPLETO_AVULSAS = lambda: [
    ("contrato.pdf", f.pdf(f.contrato_social())),
    ("federal.pdf", f.pdf(f.federal())),
    ("fgts.pdf", f.pdf(f.fgts())),
    ("cndt_e_tcu.pdf", f.pdf(f.trabalhista(), f.tcu())),
    ("estadual.pdf", f.pdf(f.estadual())),
    ("cgu.pdf", f.pdf(f.cgu(), f.cgu(cpf=f.SOCIO_CPF))),
]


def _textos(resposta):
    return [p.get_text() for p in fitz.open(stream=resposta.content, filetype="pdf")]


def test_fluxo_completo_com_certidoes_avulsas(client):
    r = _enviar(client, f.ALFA, KIT_COMPLETO_AVULSAS())
    empresa = r["empresa"]
    assert empresa["situacao"] == OK, [(i["tipo"], i["situacao"], i["observacoes"]) for i in empresa["itens"]]
    assert [(i["tipo"], i["bloco"]) for i in empresa["itens"]] == [
        ("habilitacao", 1), ("federal", 2), ("fgts", 2), ("trabalhista", 2), ("estadual", 2), ("tcu", 3), ("cgu", 3),
    ]
    assert [b["numero"] for b in empresa["blocos"]] == [1, 2, 3]

    sessao = r["sessao_id"]
    bloco2 = _textos(client.get(f"/juntada/{sessao}/bloco/11222333000181/2"))
    ordem = [next(t for t in ("TRIBUTOS FEDERAIS", "FGTS", "TRABALHISTAS", "ESTADO DE GOIAS") if t in x) for x in bloco2]
    assert ordem == ["TRIBUTOS FEDERAIS", "FGTS", "TRABALHISTAS", "ESTADO DE GOIAS"]
    assert "Conferência de certidões" not in bloco2[0]            # bloco só com documentos, sem folha de rosto
    bloco3 = _textos(client.get(f"/juntada/{sessao}/bloco/11222333000181/3"))
    assert len(bloco3) == 3 and "Consulta Consolidada" in bloco3[0]   # TCU + CGU da empresa + CGU do sócio
    assert client.get(f"/juntada/{sessao}/bloco/11222333000181/4").status_code == 404   # sem falência

    r2 = _enviar(client, f.BETA, [("federal.pdf", f.pdf(f.federal(empresa=f.BETA, valida_ate="01/10/2026")))],
                 sessao_id=sessao)
    assert r2["empresa"]["situacao"] == FALTANDO
    rel = client.get(f"/juntada/{sessao}/relatorio")
    texto = " ".join(" ".join(_textos(rel)).split())
    assert "ALFA VEICULOS LTDA" in texto and "BETA AUTOMOTORES LTDA" in texto and "Vencida em 01/10/2026" in texto
    assert "Objeto: compra de bens" in texto


# ---------------------------------------------------------------------------
# Regras da SELIT: SICAF como base da regularidade, objeto, blocos
# ---------------------------------------------------------------------------

def test_sicaf_valido_cobre_a_regularidade_e_o_bloco2_e_so_o_sicaf(client):
    r = _enviar(client, f.ALFA, [
        ("contrato.pdf", f.pdf(f.contrato_social())),
        ("sicaf.pdf", f.pdf(f.sicaf())),
        ("federal.pdf", f.pdf(f.federal())),                 # avulsa redundante: não entra no PDF
        ("tcu.pdf", f.pdf(f.tcu())),
        ("cgu.pdf", f.pdf(f.cgu(cpf=f.SOCIO_CPF))),
    ])
    itens = {i["tipo"]: i for i in r["empresa"]["itens"]}
    for tipo in ("federal", "fgts", "trabalhista", "estadual"):
        assert (itens[tipo]["situacao"], itens[tipo]["fonte"]) == (OK, "sicaf"), tipo
    assert itens["fgts"]["validade"] == "2026-10-29"
    assert "não entra no PDF" in itens["federal"]["observacoes"][1]
    assert r["empresa"]["situacao"] == OK

    bloco2 = _textos(client.get(f"/juntada/{r['sessao_id']}/bloco/11222333000181/2"))
    assert len(bloco2) == 1 and "SICAF" in bloco2[0]


def test_certidao_vencida_no_sicaf_exige_avulsa(client):
    p = dict(data_referencia="2026-11-05")                    # FGTS no SICAF vence em 29/10/2026
    sem_avulsa = _enviar(client, f.ALFA, [("sicaf.pdf", f.pdf(f.sicaf()))], **p)
    fgts = next(i for i in sem_avulsa["empresa"]["itens"] if i["tipo"] == "fgts")
    assert fgts["situacao"] == PROBLEMA and "Vencida no SICAF em 29/10/2026" in fgts["observacoes"][0]

    com_avulsa = _enviar(client, f.ALFA, [("sicaf.pdf", f.pdf(f.sicaf())),
                                          ("crf.pdf", f.pdf(f.fgts(inicio="01/11/2026", fim="30/11/2026")))],
                         sessao_id=sem_avulsa["sessao_id"], **p)
    fgts = next(i for i in com_avulsa["empresa"]["itens"] if i["tipo"] == "fgts")
    assert (fgts["situacao"], fgts["fonte"]) == (OK, "avulsa")
    bloco2 = _textos(client.get(f"/juntada/{com_avulsa['sessao_id']}/bloco/11222333000181/2"))
    assert len(bloco2) == 2 and "SICAF" in bloco2[0] and "FGTS" in bloco2[1]   # SICAF + só a avulsa que faltava


def test_sicaf_sem_a_municipal_pede_avulsa_quando_objeto_e_servico(client):
    r = _enviar(client, f.ALFA, [("sicaf.pdf", f.pdf(f.sicaf(municipal=None)))], objeto="servicos")
    itens = {i["tipo"]: i for i in r["empresa"]["itens"]}
    assert "estadual" not in itens                             # serviço: estadual não é exigida
    assert itens["municipal"]["situacao"] == FALTANDO
    assert "SICAF não informa" in itens["municipal"]["observacoes"][0]


def test_sicaf_com_impedimento_de_licitar_e_problema():
    (r,) = _conferir(f.sicaf(impedimento="Impedido até 2027"))
    assert r.situacao == PROBLEMA and "Impedimento de licitar" in r.observacoes[0]


def test_sicaf_emissao_nao_e_o_vencimento_do_cadastro():
    (c,) = _ler(f.sicaf(emitido="27/10/2026"))
    assert c.emissao == date(2026, 10, 27)
    assert c.sicaf_validades == {"federal": date(2027, 2, 9), "fgts": date(2026, 10, 29),
                                 "trabalhista": date(2027, 2, 20), "estadual": date(2027, 1, 24),
                                 "municipal": date(2027, 2, 24)}


def test_cgu_de_socio_pessoa_fisica_nao_exige_cnpj():
    (r,) = _conferir(f.cgu(cpf=f.SOCIO_CPF))
    assert r.situacao == OK and r.certidao.cpfs == ["52998224725"]


def test_falencia_vale_30_dias_por_padrao():
    (r,) = _conferir(f.falencia(data_extenso="05 de outubro de 2026"))
    assert r.certidao.validade_fim == date(2026, 11, 4)


def test_reenviar_empresa_substitui_arquivos(client):
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal(valida_ate="01/10/2026")))])
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal()))], sessao_id=r["sessao_id"])
    federal = next(i for i in r["empresa"]["itens"] if i["tipo"] == "federal")
    assert federal["situacao"] == OK and len(federal["documentos"]) == 1


def test_rejeita_arquivo_que_nao_e_pdf(client):
    r = client.post("/juntada/conferir", data={"processo_id": "p", "data_referencia": "2026-10-10",
                                               "empresa_nome": "X", "empresa_cnpj": f.ALFA[1]},
                    files=[("arquivos", ("a.pdf", b"nao sou pdf", "application/pdf"))])
    assert r.status_code == 400


def test_identificar_empresa_pelas_certidoes(client):
    r = client.post("/juntada/identificar", files=[("arquivos", ("a.pdf", f.pdf(f.fgts(), f.tcu()), "application/pdf"))])
    assert r.json()["cnpj"] == "11222333000181"
    assert r.json()["razao_social"] == "ALFA VEICULOS LTDA"


def test_consulta_tcu_desativada_responde_503(client):
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal()))])
    resp = client.post(f"/juntada/{r['sessao_id']}/tcu", data={"empresa_cnpj": f.ALFA[1]})
    assert resp.status_code == 503 and "não tem acesso à internet" in resp.json()["detail"]
    assert client.get("/juntada/config").json()["consulta_tcu_ativa"] is False


def test_consulta_tcu_ativa_acrescenta_certidao(client, monkeypatch):
    """Fase 2: resposta no formato real da API do TCU (JSON com o PDF em base64)."""
    monkeypatch.setenv("JUNTADA_CONSULTA_TCU", "1")
    resposta = json.dumps({"certidaoPDF": base64.b64encode(f.pdf(f.tcu())).decode(), "certidoes": []}).encode()

    class _Resposta:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return resposta

    chamadas = []
    monkeypatch.setattr("app.tcu.urllib.request.urlopen", lambda url, timeout: chamadas.append(url) or _Resposta())

    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal()))])
    resp = client.post(f"/juntada/{r['sessao_id']}/tcu", data={"empresa_cnpj": f.ALFA[1]})
    assert resp.status_code == 200, resp.text
    assert chamadas == ["https://certidoes-apf.apps.tcu.gov.br/api/rest/publico/certidoes/11222333000181?seEmitirPDF=true"]
    tcu = next(i for i in resp.json()["empresa"]["itens"] if i["tipo"] == "tcu")
    assert tcu["situacao"] == OK


def test_sessao_inexistente(client):
    assert client.get("/juntada/" + "0" * 32 + "/relatorio").status_code == 404
    assert client.get("/juntada/../../etc/relatorio").status_code == 404


# ---------------------------------------------------------------------------
# Conferência manual pelo servidor
# ---------------------------------------------------------------------------

def _item(resposta, tipo):
    return next(i for i in resposta["empresa"]["itens"] if i["tipo"] == tipo)


def test_conferencia_manual_resolve_tcu_pendente_e_fica_registrada(client):
    r = _enviar(client, f.ALFA, [
        ("certidoes.pdf", f.pdf(f.federal(), f.fgts(), f.trabalhista())),
        ("tcu.pdf", f.pdf(f.tcu(cnj="Sistema do CNJ está indisponível"))),
    ], obrigatorias="federal,fgts,trabalhista,tcu")
    sessao = r["sessao_id"]
    assert r["empresa"]["situacao"] == ATENCAO

    curta = client.post(f"/juntada/{sessao}/manual", data={"empresa_cnpj": "11222333000181", "tipo": "tcu", "justificativa": "ok"})
    assert curta.status_code == 400

    justificativa = "CNIA consultado diretamente no site do CNJ em 20/10/2026: nada consta."
    m = client.post(f"/juntada/{sessao}/manual",
                    data={"empresa_cnpj": "11222333000181", "tipo": "tcu", "justificativa": justificativa}).json()
    tcu = _item(m, "tcu")
    assert (tcu["situacao"], tcu["situacao_automatica"]) == (OK, ATENCAO)
    assert m["empresa"]["situacao"] == OK
    assert justificativa in tcu["observacoes"][0]

    rel = client.get(f"/juntada/{sessao}/relatorio").content
    texto = " ".join(" ".join(p.get_text() for p in fitz.open(stream=rel, filetype="pdf")).split())
    assert "conferido pelo servidor" in texto and "CNIA consultado diretamente" in texto
    assert "Situação apontada pelo sistema: Conferir" in texto

    desfeito = client.delete(f"/juntada/{sessao}/manual/11222333000181/tcu").json()
    assert _item(desfeito, "tcu")["situacao"] == ATENCAO


def test_conferencia_manual_de_certidao_dispensada(client):
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal()))])
    m = client.post(f"/juntada/{r['sessao_id']}/manual", data={
        "empresa_cnpj": "11222333000181", "tipo": "fgts",
        "justificativa": "Empresa sem empregados; edital dispensa o CRF (item 8.3)."}).json()
    assert _item(m, "fgts")["situacao"] == OK and _item(m, "fgts")["situacao_automatica"] == FALTANDO


def test_reenviar_arquivos_apaga_decisoes_manuais(client):
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal(valida_ate="01/10/2026")))])
    client.post(f"/juntada/{r['sessao_id']}/manual", data={
        "empresa_cnpj": "11222333000181", "tipo": "federal", "justificativa": "Conferida a nova certidão no site da Receita."})
    r = _enviar(client, f.ALFA, [("federal.pdf", f.pdf(f.federal(valida_ate="01/10/2026")))], sessao_id=r["sessao_id"])
    assert _item(r, "federal")["situacao"] == PROBLEMA and _item(r, "federal")["conferencia_manual"] is None


def test_arquivos_recebidos_com_hash(client):
    import hashlib
    conteudo = f.pdf(f.federal())
    r = _enviar(client, f.ALFA, [("federal.pdf", conteudo)])
    assert r["empresa"]["arquivos"] == [{"arquivo": "federal.pdf", "paginas": 1, "sha256": hashlib.sha256(conteudo).hexdigest()}]


def test_nome_do_download_sem_acentos(client):
    """Acento no Content-Disposition quebrava o download do bloco 1 ("Habilitação Jurídica")."""
    r = _enviar(client, ("AÇÚCAR & CIA LTDA", f.ALFA[1]), [("contrato.pdf", f.pdf(f.contrato_social()))])
    resp = client.get(f"/juntada/{r['sessao_id']}/bloco/11222333000181/1")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="bloco1_Habilitacao_Juridica_ACUCAR_CIA_LTDA.pdf"'


def test_estadual_goias_data_sem_de_e_validade_em_dias():
    """Layout real de Goiás: "GOIANIA, 5 OUTUBRO DE 2026" + "VALIDA POR 120 DIAS"."""
    (c,) = ler_pdf([f.estadual()], "estadual.pdf")
    assert c.tipo == "estadual" and c.resultado == "negativa"
    assert c.emissao == date(2026, 10, 5) and c.validade_fim == date(2027, 2, 2)


def test_cgu_empresa_layout_real():
    (c,) = ler_pdf([f.cgu()], "cgu.pdf")
    assert c.tipo == "cgu" and c.resultado == "negativa"
    assert c.emissao == date(2026, 10, 5) and c.cnpjs == ["11222333000181"]


def test_municipal_goiania_layout_real():
    (c,) = ler_pdf([f.municipal_goiania()], "municipal.pdf")
    assert c.tipo == "municipal" and c.resultado == "negativa"
    assert c.emissao == date(2026, 11, 4) and c.validade_fim == date(2027, 2, 1)


def test_falencia_tjgo_layout_real_duas_paginas():
    (c,) = ler_pdf(list(f.falencia_tjgo()), "falencia.pdf")
    assert c.tipo == "falencia" and c.paginas == [1, 2] and c.resultado == "negativa"
    assert c.emissao == date(2025, 11, 28) and c.cnpjs == ["11222333000181"]
    par = Parametros(data_referencia=date(2025, 12, 29), obrigatorias=["falencia"])
    assert conferir_certidao(c, "11222333000181", par).situacao == PROBLEMA   # 30 dias: venceu em 28/12/2025


def test_identificacao_na_certidao_de_falencia_tjgo():
    """"Sociedades Empresariais, ME e EPP" não é razão social; o nome vem depois de "Requerente"."""
    from app.identificacao import identificar
    r = identificar(list(f.falencia_tjgo()))
    assert r["cnpj"] == "11222333000181" and r["razao_social"] == f.ALFA[0]


def test_identificacao_ignora_nome_da_certificadora_da_assinatura():
    """O carimbo de assinatura digital repete o nome da certificadora em toda página; não é a licitante."""
    from app.identificacao import identificar
    carimbo = "v3.0 - CERTIFICADORA FICTICIA Blockchain Documentos Digitais e Serviços LTDA"
    r = identificar([f.contrato_social() + "\n" + carimbo, carimbo, carimbo, carimbo])
    assert r["cnpj"] == "11222333000181" and r["razao_social"] == f.ALFA[0]
