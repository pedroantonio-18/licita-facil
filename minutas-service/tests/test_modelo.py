from app.modelo import ler_modelo, numerar
from app.montagem import Decisoes, montar
from tests import modelo_ficticio


def _modelo():
    return ler_modelo(modelo_ficticio.docx())


def _por_texto(blocos, inicio):
    return next(b for b in blocos if b.texto.startswith(inicio))


def test_leitura_estrutura_versao_e_notas():
    m = _modelo()
    assert m.tipo == "aviso_dispensa" and m.versao == "MAR/2026"
    assert len(m.orientacoes) == 1 and "LEITURA OBRIGATÓRIA" in m.orientacoes[0]
    titulos = [b.texto for b in m.blocos if b.tipo == "titulo"]
    assert titulos == ["DO OBJETO", "DO REGISTRO DE PREÇOS", "DA PARTICIPAÇÃO", "DAS DISPOSIÇÕES GERAIS"]
    rp = _por_texto(m.blocos, "DO REGISTRO DE PREÇOS")
    assert rp.notas == ["Nota explicativa: adotar somente se houver registro de preços."]
    assert _por_texto(m.blocos, "As regras do registro").tema_integral == "registro_precos"
    assert _por_texto(m.blocos, "O objeto é").tem_variavel
    assert _por_texto(m.blocos, "pessoas físicas").tipo == "item"          # "Nível 3-R" herda o nível 3
    assert _por_texto(m.blocos, "OU").tipo == "ou"


def test_numeracao_do_modelo_ignora_preambulo_sem_numero():
    m = _modelo()
    n = numerar(m.blocos)
    assert _por_texto(m.blocos, "Torna-se público").tipo == "paragrafo"     # numId 0 no parágrafo
    assert n[_por_texto(m.blocos, "DA PARTICIPAÇÃO").id] == "3."
    assert n[_por_texto(m.blocos, "pessoas físicas").id] == "3.1.2."
    assert n[_por_texto(m.blocos, "Ver item 2.1").id] == "4.1."


def test_sem_registro_de_precos_renumera_e_corrige_referencias():
    mi = montar(_modelo(), Decisoes())
    titulos = [(b.numero, b.texto) for b in mi.titulos]
    assert titulos == [("1.", "DO OBJETO"), ("2.", "DA PARTICIPAÇÃO"), ("3.", "DAS DISPOSIÇÕES GERAIS")]
    assert any("Registro de preços" in r.motivo for r in mi.removidos)

    impedimento = _por_texto(mi.blocos, "O impedimento")
    assert "item 2.1.1 vale" in impedimento.texto and impedimento.referencias == ["3.1.1 → 2.1.1"]
    assert impedimento.situacao == "referencia"

    # Trecho turquesa no meio do parágrafo sai; referências múltiplas são ajustadas
    itens = _por_texto(mi.blocos, "Os itens")
    assert itens.texto == "Os itens 2.1.1 e 2.1.2 não impedem a contratação."
    assert itens.situacao == "alterado"

    # Referência a item que saiu (2.1 era registro de preços) vira pendência
    assert any("2.1 do modelo, que foi removido" in p.descricao for p in mi.pendencias)


def test_com_registro_de_precos_mantem_tudo():
    mi = montar(_modelo(), Decisoes(temas={"registro_precos"}))
    assert [b.texto for b in mi.titulos][1] == "DO REGISTRO DE PREÇOS"
    assert _por_texto(mi.blocos, "O impedimento").referencias == []
    assert "nem a adesão à ata" in _por_texto(mi.blocos, "Os itens").texto


def test_alternativas_ou_e_campos_viram_pendencias():
    mi = montar(_modelo(), Decisoes())
    assert all(b.tipo != "ou" for b in mi.blocos)
    assert any("redações alternativas" in p.descricao for p in mi.pendencias)
    campos = [p for p in mi.pendencias if "não preenchido" in p.descricao]
    assert len(campos) >= 3                      # órgão, número do aviso, objeto

    # Escolhida a alternativa e preenchidos os campos, as pendências somem
    m = _modelo()
    dividida = _por_texto(m.blocos, "A licitação será dividida")
    objeto = _por_texto(m.blocos, "O objeto é")
    mi = montar(m, Decisoes(remover={dividida.id: "Item único"},
                            textos={objeto.id: "O objeto é a contratação de serviço fictício."},
                            motivos={objeto.id: "Conforme o TR"}, origem={objeto.id: "ia"}))
    assert not any("redações alternativas" in p.descricao for p in mi.pendencias)
    assert not any(p.bloco == objeto.id for p in mi.pendencias)
    alterado = _por_texto(mi.blocos, "O objeto é")
    assert alterado.situacao == "alterado" and alterado.origem == "ia" and not alterado.alterou_texto_fixo


def test_alterar_texto_fixo_e_sinalizado():
    m = _modelo()
    fixo = _por_texto(m.blocos, "Havendo mais de um item")
    mi = montar(m, Decisoes(textos={fixo.id: "Texto fixo reescrito."}))
    assert _por_texto(mi.blocos, "Texto fixo reescrito").alterou_texto_fixo


def test_texto_nao_decidido_e_copiado_literalmente():
    m = _modelo()
    mi = montar(m, Decisoes())
    originais = {b.id: b.texto for b in m.blocos}
    for b in mi.blocos:
        if b.situacao == "igual":
            assert b.texto == originais[b.id]


def test_marcador_preto_xx_vira_pendencia_e_vai_em_amarelo():
    from app.saida_sei import html_sei
    corpo = [modelo_ficticio.par("DO OBJETO", estilo="Nivel01"),
             modelo_ficticio.par("Para os itens XX, XX e XX, a participação é exclusiva a ME/EPP.", estilo="Nivel2"),
             modelo_ficticio.par("Multa de .......% sobre o valor.", estilo="Nivel2"),
             modelo_ficticio.par("Texto sem marcador.", estilo="Nivel2")]
    mi = montar(ler_modelo(modelo_ficticio.docx(corpo)), Decisoes())
    assert [p.numero for p in mi.pendencias] == ["1.1.", "1.2."]
    html = html_sei(mi)
    assert html.count('background-color: #ffff00;">XX</span>') == 3 and '#ffff00;">.......</span>' in html


def test_trecho_opcional_vermelho_mantido_ou_retirado():
    corpo = [modelo_ficticio.par("DO OBJETO", estilo="Nivel01"),
             modelo_ficticio.par("Conforme o Termo de Referência,", modelo_ficticio.run(" Projeto Básico e Projeto Executivo", vermelho=True),
                                 ", assumindo o proponente o compromisso.", estilo="Nivel2")]
    m = ler_modelo(modelo_ficticio.docx(corpo))
    cid = m.blocos[1].campos[0].id
    from app.montagem import MANTER_CAMPO
    manteve = montar(m, Decisoes(campos={cid: MANTER_CAMPO}))
    assert manteve.blocos[1].texto == "Conforme o Termo de Referência, Projeto Básico e Projeto Executivo, assumindo o proponente o compromisso."
    assert manteve.pendencias == []
    tirou = montar(m, Decisoes(campos={cid: ""}))
    assert tirou.blocos[1].texto == "Conforme o Termo de Referência, assumindo o proponente o compromisso."
    assert tirou.pendencias == []


def test_pontuacao_vermelha_solta_nao_e_campo():
    corpo = [modelo_ficticio.par("DO OBJETO", estilo="Nivel01"),
             modelo_ficticio.par("sociedades cooperativas", modelo_ficticio.run(".", vermelho=True), estilo="Nivel3")]
    m = ler_modelo(modelo_ficticio.docx(corpo))
    assert m.blocos[1].campos == [] and not m.blocos[1].tem_variavel
    assert montar(m, Decisoes()).pendencias == []


def test_preencher_campo_preserva_espaco_que_fazia_parte_do_campo():
    corpo = [modelo_ficticio.par("DO OBJETO", estilo="Nivel01"),
             modelo_ficticio.par("A validade não será inferior a ", modelo_ficticio.run("60 (sessenta)", vermelho=True),
                                 modelo_ficticio.run(" ", vermelho=True), "dias.", estilo="Nivel2")]
    m = ler_modelo(modelo_ficticio.docx(corpo))
    cid = m.blocos[1].campos[0].id
    assert montar(m, Decisoes(campos={cid: "90 (noventa)"})).blocos[1].texto == "A validade não será inferior a 90 (noventa) dias."
