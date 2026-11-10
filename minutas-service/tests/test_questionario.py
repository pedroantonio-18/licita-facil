from app.modelo import ler_modelo
from app.montagem import Decisoes, montar
from app.questionario import aplicar, perguntas_para
from tests.modelo_ficticio import docx, par, run

v = lambda t: run(t, vermelho=True)


def _modelo():
    return ler_modelo(docx([
        par("DO OBJETO", estilo="Nivel01"),
        par("O lance deverá ser ofertado pelo ", v("[valor unitário]"), v(" OU "), v("[percentual de desconto]"), " do item.", estilo="Nivel2"),
        par("DA PARTICIPAÇÃO", estilo="Nivel01"),
        par("A participação ocorrerá pelo sistema.", estilo="Nivel2"),                                           # 2.1
        par("Para os itens XX, XX e XX, a participação é exclusiva a microempresas e empresas de pequeno porte.", estilo="Nvel2-Opcional"),  # 2.2
        par("A obtenção do benefício a que se refere o item anterior fica limitada às ME/EPP.", estilo="Nvel3-R"),   # 2.2.1
        par("Será concedido tratamento favorecido para as microempresas e empresas de pequeno porte.", estilo="Nvel3-R"),  # 2.2.2
        par("Não poderão participar:", estilo="Nivel2"),                                                           # 2.3
        par("pessoas jurídicas reunidas em consórcio;", estilo="Nvel3-R"),
        par("sociedades cooperativas;", estilo="Nvel3-R"),
        par("pessoas físicas.", estilo="Nvel3-R"),
        par("A vedação de que trata o item 2.3 vale também para terceiros.", estilo="Nivel2"),
        par("DA CONTRATAÇÃO", estilo="Nivel01"),
        par("O adjudicatário terá o prazo de XX (", v("valor por extenso"), ") dias úteis para assinar o ",
            v("Termo de Contrato"), v(" OU "), v("aceitar instrumento equivalente"), ".", estilo="Nivel2"),
        par("O Aceite da Nota de Empenho implica o reconhecimento de que:", estilo="Nvel2-Opcional"),
        par("referida Nota está substituindo o contrato, aplicando-se as disposições da ", v("Lei nº 14.133, de 2021"), ";", estilo="Nvel3-R"),
        par("DOS ANEXOS", estilo="Nivel01"),
        par("ANEXO III – Minuta de Termo de Contrato;", estilo="Nvel3-R"),
        par("ANEXO V – (...)", estilo="Nvel3-R"),
    ]))


def _texto(mi):
    return [b.texto for b in mi.blocos]


def test_perguntas_por_tipo():
    ids = [p["id"] for p in perguntas_para("aviso_dispensa")]
    assert "instrumento" in ids and "vistoria" not in ids
    assert "vistoria" in [p["id"] for p in perguntas_para("edital_pregao")]


def test_regras_que_saem_do_formulario_sem_pergunta():
    m = _modelo()
    mi = montar(m, aplicar(m, {}, {"criterio": "menor preço global", "margem_preferencia": "NÃO"}))
    assert "O lance deverá ser ofertado pelo valor unitário do item." in _texto(mi)
    assert "ANEXO V – (...)" not in _texto(mi)


def test_nota_de_empenho():
    m = _modelo()
    mi = montar(m, aplicar(m, {"instrumento": "empenho"}))
    t = _texto(mi)
    assert any(x.endswith("para aceitar instrumento equivalente.") for x in t)
    assert "ANEXO III – Minuta de Termo de Contrato;" not in t
    nota = next(x for x in t if x.startswith("referida Nota"))
    assert nota.endswith("Lei nº 14.133, de 2021;")
    pendentes = [next(b.texto for b in mi.blocos if b.id == p.bloco) for p in mi.pendencias]
    assert not any(x.startswith(("O Aceite", "referida", "ANEXO III")) for x in pendentes)
    prazo = next(x for x in pendentes if x.startswith("O adjudicatário"))
    assert "XX (valor por extenso)" in prazo            # só o prazo continua para preencher


def test_termo_de_contrato_remove_aceite_e_subitens():
    m = _modelo()
    mi = montar(m, aplicar(m, {"instrumento": "contrato"}))
    t = _texto(mi)
    assert not any(x.startswith(("O Aceite", "referida Nota")) for x in t)
    assert "ANEXO III – Minuta de Termo de Contrato;" in t
    assert any(x.endswith("para assinar o Termo de Contrato.") for x in t)


def test_me_epp_nenhum_mantem_tratamento_favorecido_no_lugar_do_item():
    m = _modelo()
    mi = montar(m, aplicar(m, {"me_epp_itens": "nenhum"}))
    favorecido = next(b for b in mi.blocos if b.texto.startswith("Será concedido"))
    assert favorecido.numero == "2.2."                     # subiu para o lugar da exclusividade por item
    assert not any(b.texto.startswith(("Para os itens", "A obtenção")) for b in mi.blocos)
    assert any(b.texto.startswith("A vedação de que trata o item 2.3 ") for b in mi.blocos)   # referência intacta


def test_me_epp_todos_reescreve_sem_marcadores():
    m = _modelo()
    mi = montar(m, aplicar(m, {"me_epp_itens": "todos"}))
    assert "A participação é exclusiva a microempresas e empresas de pequeno porte." in _texto(mi)


def test_participacao_admitir_e_tirar_da_lista_de_vedados():
    m = _modelo()
    mi = montar(m, aplicar(m, {"consorcio": "nao", "cooperativas": "sim", "pessoa_fisica": "nao"}))
    t = _texto(mi)
    assert "pessoas jurídicas reunidas em consórcio;" in t and "pessoas físicas." in t
    assert "sociedades cooperativas;" not in t
    assert not any(p.tipo == "opcional" and next(b.texto for b in mi.blocos if b.id == p.bloco).startswith(("pessoas", "sociedades"))
                   for p in mi.pendencias)


def test_decisao_do_servidor_prevalece_sobre_o_questionario(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from routers import minutas
    (tmp_path / "aviso-q.docx").write_bytes(docx([par("AVISO DE CONTRATAÇÃO DIRETA"),
                                                  par("DA PARTICIPAÇÃO", estilo="Nivel01"),
                                                  par("Não poderão participar:", estilo="Nivel2"),
                                                  par("sociedades cooperativas;", estilo="Nvel3-R")]))
    monkeypatch.setattr(minutas, "MODELOS_DIR", tmp_path)
    from main import app
    c = TestClient(app)
    config = c.get("/minutas/config").json()
    assert any(p["id"] == "cooperativas" for p in config["modelos"][0]["perguntas"])
    coop = next(b["id"] for b in c.get("/minutas/modelos/aviso-q/estrutura").json()["blocos"] if b["texto"].startswith("sociedades"))
    base = {"modelo_id": "aviso-q", "respostas": {"cooperativas": "sim"}}
    r = c.post("/minutas/montar", json=base).json()
    assert not any(b["id"] == coop for b in r["blocos"])
    assert any(x["id"] == coop and x["motivo"].startswith("Questionário") for x in r["removidos"])
    r = c.post("/minutas/montar", json={**base, "decisoes": {"manter": [coop]}}).json()
    assert any(b["id"] == coop for b in r["blocos"])
