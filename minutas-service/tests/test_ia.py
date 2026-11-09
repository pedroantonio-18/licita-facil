import json

from app.ia import evidencia_no_tr, montar_prompt, pendencias_para_ia, validar
from app.modelo import ler_modelo
from app.montagem import Decisoes, montar
from tests.modelo_ficticio import docx, par, run

TR = """TERMO DE REFERÊNCIA (FICTÍCIO)
1. O objeto é a prestação de serviço fictício de jardinagem, em lote único, pelo critério de menor preço global.
2. O prazo de validade da proposta será de 90 (noventa) dias.
3. Não será admitida a participação de empresas reunidas em consórcio, dada a baixa complexidade do objeto.
4. O lance será ofertado pelo valor global do lote.
5. Não há itens de participação exclusiva para ME/EPP, por se tratar de lote único.
""" + "Texto de preenchimento do termo de referência. " * 10


def _modelo():
    v = lambda t: run(t, vermelho=True)
    return ler_modelo(docx([
        par("DO OBJETO", estilo="Nivel01"),
        par("O lance deverá ser ofertado pelo ", v("[valor unitário]"), v(" OU "), v("[percentual de desconto]"), " do item.", estilo="Nivel2"),
        par("O prazo de validade da proposta não será inferior a ", v("XX"), v(" "), "(", v("valor por extenso"), ") dias.", estilo="Nivel2"),
        par("Conforme o Termo de Referência,", v(" Projeto Básico e Projeto Executivo"), ", assumindo o compromisso.", estilo="Nivel2"),
        par("DA PARTICIPAÇÃO", estilo="Nivel01"),
        par("Não poderão participar:", estilo="Nivel2"),
        par(v("pessoas jurídicas reunidas em consórcio, nos termos do art. 15 da Lei nº 14.133, de 2021, conforme o caso concreto;"), estilo="Nivel3"),
        par("Para os itens XX, XX e XX, a participação é exclusiva a ME/EPP.", estilo="Nivel2"),
        par("A licitação será dividida em itens.", estilo="Nivel2"),
        par("OU", estilo="ou"),
        par("A licitação será realizada em lote único.", estilo="Nivel2"),
    ]))


def _contexto():
    m = _modelo()
    mi = montar(m, Decisoes())
    return m, mi, pendencias_para_ia(m, mi, set())


def _id(m, inicio):
    return next(b.id for b in m.blocos if b.texto.startswith(inicio))


def test_pendencias_e_prompt():
    m, mi, itens = _contexto()
    tipos = sorted(it.tipo for it in itens)
    assert tipos == ["alternativa", "campo", "campo", "campo", "clausula", "marcador"]
    lance = next(it for it in itens if it.texto.startswith("O lance"))
    assert lance.campos[0]["tipo"] == "escolha" and lance.campos[0]["opcoes"] == ["valor unitário", "percentual de desconto"]
    assert "⟦" in lance.texto
    trecho = next(it for it in itens if it.texto.startswith("Conforme"))
    assert trecho.campos[0]["tipo"] == "trecho_opcional"
    prompt = montar_prompt(m, itens, TR, {"objeto": "serviço fictício", "signatario": "NÃO VAI"}, "Aviso")
    assert "PENDÊNCIAS" in prompt and "jardinagem" in prompt and "NÃO VAI" not in prompt


def test_decisoes_validas_sao_aplicadas():
    m, mi, itens = _contexto()
    lance, validade, trecho = _id(m, "O lance"), _id(m, "O prazo de validade"), _id(m, "Conforme")
    consorcio, itens_me, dividida, unico = (_id(m, "pessoas jurídicas reunidas"), _id(m, "Para os itens"),
                                            _id(m, "A licitação será dividida"), _id(m, "A licitação será realizada"))
    resposta = json.dumps({"decisoes": [
        {"bloco": lance, "acao": "preencher", "campos": {f"{lance}.1": "valor unitário"},
         "motivo": "O TR adota lance por valor do lote", "evidencia": "O lance será ofertado pelo valor global do lote."},
        {"bloco": validade, "acao": "preencher", "campos": {f"{validade}.1": "90 (noventa)"},
         "motivo": "Prazo definido no item 2 do TR", "evidencia": "O prazo de validade da proposta será de 90 (noventa) dias"},
        {"bloco": trecho, "acao": "retirar_trecho", "campo": f"{trecho}.1", "motivo": "Serviço comum, sem projeto básico"},
        {"bloco": consorcio, "acao": "manter", "motivo": "O TR veda consórcio expressamente",
         "evidencia": "Não será admitida a participação de empresas reunidas em consórcio"},
        {"bloco": itens_me, "acao": "remover", "motivo": "Lote único, sem itens exclusivos para ME/EPP",
         "evidencia": "Não há itens de participação exclusiva para ME/EPP"},
        {"bloco": unico, "acao": "manter", "motivo": "O objeto é em lote único", "evidencia": "em lote único"},
    ]}, ensure_ascii=False)
    r = validar(itens, resposta, TR)
    assert r.descartes == [] and len(r.aplicadas) == 6
    final = montar(m, r.decisoes)
    textos = [b.texto for b in final.blocos]
    assert "O lance deverá ser ofertado pelo valor unitário do item." in textos
    assert "O prazo de validade da proposta não será inferior a 90 (noventa) dias." in textos
    assert "Conforme o Termo de Referência, assumindo o compromisso." in textos
    assert any(t.startswith("pessoas jurídicas reunidas em consórcio") for t in textos)
    assert not any(t.startswith("Para os itens") for t in textos)
    assert "A licitação será realizada em lote único." in textos and "A licitação será dividida em itens." not in textos
    assert final.pendencias == []
    origem = next(b for b in final.blocos if b.texto.startswith("O prazo"))
    assert origem.origem == "ia" and "TR:" in origem.motivo


def test_sugestoes_invalidas_sao_descartadas_com_motivo():
    m, mi, itens = _contexto()
    lance, validade, itens_me = _id(m, "O lance"), _id(m, "O prazo de validade"), _id(m, "Para os itens")
    resposta = json.dumps({"decisoes": [
        {"bloco": "B999", "acao": "remover", "motivo": "bloco que não existe na minuta"},
        {"bloco": lance, "acao": "preencher", "campos": {f"{lance}.1": "valor por quilo"},
         "motivo": "Opção inventada pela IA", "evidencia": "O lance será ofertado pelo valor global do lote."},
        {"bloco": validade, "acao": "preencher", "campos": {f"{validade}.1": "60 (sessenta)"},
         "motivo": "Evidência que não está no TR", "evidencia": "a proposta valerá por sessenta dias corridos"},
        {"bloco": itens_me, "acao": "reescrever", "texto": "Para os itens XX e 2, exclusivo.",
         "motivo": "Reescrita deixando marcador", "evidencia": "em lote único"},
    ]}, ensure_ascii=False)
    r = validar(itens, resposta, TR)
    motivos = {d["bloco"]: d["motivo"] for d in r.descartes}
    assert "não está entre as pendências" in motivos["B999"]
    assert "não é uma das opções" in motivos[lance]
    assert "não foi encontrado no TR" in motivos[validade]
    assert "marcador" in motivos[itens_me]
    assert r.aplicadas == []


def test_reescrita_muito_diferente_e_sem_evidencia_sao_recusadas():
    m, mi, itens = _contexto()
    itens_me = _id(m, "Para os itens")
    r = validar(itens, json.dumps({"decisoes": [
        {"bloco": itens_me, "acao": "reescrever", "texto": "Fica proibido o uso de celulares durante a sessão pública.",
         "motivo": "Texto sem relação com o modelo", "evidencia": "em lote único"}]}), TR)
    assert "muito diferente" in r.descartes[0]["motivo"]
    r = validar(itens, json.dumps({"decisoes": [
        {"bloco": itens_me, "acao": "reescrever", "texto": "Para os itens 1 e 2, a participação é exclusiva a ME/EPP.",
         "motivo": "Itens definidos sem citar o TR"}]}), TR)
    assert "Sem trecho do TR" in r.descartes[0]["motivo"]


def test_resposta_que_nao_e_json_e_sem_informacao():
    _, _, itens = _contexto()
    assert "não é um JSON" in validar(itens, "não sei responder", TR).descartes[0]["motivo"]
    bloco = itens[0].bloco
    r = validar(itens, "```json\n" + json.dumps({"decisoes": [], "sem_informacao": [{"bloco": bloco, "motivo": "TR omisso"}]}) + "\n```", TR)
    assert r.sem_informacao == [{"bloco": bloco, "numero": itens[0].numero, "motivo": "TR omisso"}]


def test_evidencia_tolera_quebra_de_linha_do_pdf():
    tr = "O prazo de validade da pro-\nposta será de 90 (noventa) dias, contados da sessão."
    assert evidencia_no_tr("O prazo de validade da proposta será de 90 (noventa) dias", " ".join(tr.lower().split()))
    assert not evidencia_no_tr("curto", tr.lower())


def test_api_prompt_e_validar(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from routers import minutas
    (tmp_path / "aviso-ia.docx").write_bytes(docx([
        par("ÓRGÃO OU ENTIDADE PÚBLICA"), par("AVISO DE CONTRATAÇÃO DIRETA Nº ", run("[XX/AAAA]", vermelho=True)),
        par("DO OBJETO", estilo="Nivel01"),
        par("O prazo de validade da proposta não será inferior a ", run("XX", vermelho=True), " dias.", estilo="Nivel2"),
    ]))
    monkeypatch.setattr(minutas, "MODELOS_DIR", tmp_path)
    from main import app
    c = TestClient(app)
    base = {"modelo_id": "aviso-ia", "dados": {"numero": "1/2026"}, "texto_tr": TR}
    assert c.post("/minutas/ia/prompt", json={**base, "texto_tr": "curto"}).status_code == 400
    p = c.post("/minutas/ia/prompt", json=base).json()
    assert p["aplicavel"] and p["pendencias"] == 1
    bloco = next(b["id"] for b in c.get("/minutas/modelos/aviso-ia/estrutura").json()["blocos"] if b["texto"].startswith("O prazo"))
    resposta = json.dumps({"decisoes": [{"bloco": bloco, "acao": "preencher", "campos": {f"{bloco}.1": "90 (noventa)"},
                                         "motivo": "Prazo do item 2 do TR", "evidencia": "validade da proposta será de 90 (noventa) dias"}]})
    v = c.post("/minutas/ia/validar", json={**base, "resposta": resposta}).json()
    assert v["descartes"] == [] and v["decisoes"]["campos"] == {f"{bloco}.1": "90 (noventa)"}
    final = c.post("/minutas/montar", json={**base, "decisoes": v["decisoes"]}).json()
    assert final["resumo"]["pendencias"] == 0


def test_formato_relevancia_e_valor_do_modelo():
    v = lambda t: run(t, vermelho=True)
    m = ler_modelo(docx([
        par("DO OBJETO", estilo="Nivel01"),
        par("A multa será recolhida no prazo de ", v("XX"), v(" "), "(", v("valor por extenso"), ") dias.", estilo="Nivel2"),
        par("Aplicam-se as disposições da ", v("Lei nº 14.133, de 2021"), ".", estilo="Nivel2"),
        par("O adjudicatário terá prazo de ", v("XX"), " dias úteis.", estilo="Nivel2"),
        par("pessoas físicas.", estilo="Nvel3-R"),
    ]))
    mi = montar(m, Decisoes())
    itens = pendencias_para_ia(m, mi, set())
    multa, lei, prazo, fisicas = (m.blocos[i].id for i in (1, 2, 3, 4))
    assert next(it for it in itens if it.bloco == multa).campos[0]["formato"].startswith("número")
    tr = TR + " 4.2. O adjudicatário terá o prazo de 5 (cinco) dias úteis para aceitar a Nota de Empenho."
    r = validar(itens, json.dumps({"decisoes": [
        {"bloco": multa, "acao": "preencher", "campos": {f"{multa}.1": "trinta"}, "motivo": "Prazo de multa do TR",
         "evidencia": "O prazo de validade da proposta será de 90 (noventa) dias"},
        {"bloco": lei, "acao": "preencher", "campos": {f"{lei}.1": "Lei nº 14.133, de 2021"}, "motivo": "Mantido o texto do modelo"},
        {"bloco": prazo, "acao": "preencher", "campos": {f"{prazo}.1": "10"}, "motivo": "Prazo para aceitar a nota",
         "evidencia": "dada a baixa complexidade do objeto"},
        {"bloco": fisicas, "acao": "manter", "motivo": "Redação padrão da AGU mantida"},
    ]}, ensure_ascii=False), tr)
    motivos = {d["bloco"]: d["motivo"] for d in r.descartes}
    assert "fora do padrão do modelo" in motivos[multa]
    assert "não menciona o valor" in motivos[prazo]
    assert {a["bloco"] for a in r.aplicadas} == {lei, fisicas}       # sem trecho do TR: repete o modelo / mantém opcional


def test_remocao_sem_trecho_do_assunto_e_valor_inventado_sao_recusados():
    m, mi, itens = _contexto()
    consorcio, itens_me = _id(m, "pessoas jurídicas reunidas"), _id(m, "Para os itens")
    r = validar(itens, json.dumps({"decisoes": [
        # cláusula vermelha adotada citando trecho que não fala de consórcio
        {"bloco": consorcio, "acao": "manter", "motivo": "Mantida a vedação padrão", "evidencia": "O lance será ofertado pelo valor global do lote."},
        # reescrita com percentual que não está no trecho citado
        {"bloco": itens_me, "acao": "reescrever", "texto": "Para os itens 1, 2 e 3, a participação é exclusiva a ME/EPP.",
         "motivo": "Itens definidos no TR", "evidencia": "Não há itens de participação exclusiva para ME/EPP"},
    ]}, ensure_ascii=False), TR)
    motivos = {d["bloco"]: d["motivo"] for d in r.descartes}
    assert "fica para decisão do servidor" in motivos[consorcio]
    assert "valores que não estão no trecho" in motivos[itens_me]
    assert r.aplicadas == []


def test_reescrever_para_negar_clausula_e_recusado():
    m, mi, itens = _contexto()
    itens_me = _id(m, "Para os itens")
    r = validar(itens, json.dumps({"decisoes": [
        {"bloco": itens_me, "acao": "reescrever", "texto": "Para o lote único, a participação não é exclusiva a ME/EPP.",
         "motivo": "Lote único sem exclusividade", "evidencia": "Não há itens de participação exclusiva para ME/EPP"}]}), TR)
    assert "a ação é remover" in r.descartes[0]["motivo"]
