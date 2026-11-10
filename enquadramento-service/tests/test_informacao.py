from decimal import Decimal as D

from app.informacao import DadosInformacao, html_sei, montar
from app.regras import Demanda, Item, enquadrar


def _texto(ps):
    return "\n".join(p.texto for p in ps)


def _gerar(natureza, itens, demandas=(), **dados):
    demandas = list(demandas)
    e = enquadrar(natureza, itens, demandas, "2026")
    return e, montar(DadosInformacao(**dados), e, natureza, itens, demandas)


def test_dispensa_completa():
    e, ps = _gerar("bem", [Item("Água fictícia", D("18000"))], objeto="aquisição de água fictícia",
                   doc_referencia="DFD (00000001)", relatorio="00000002", metodologia="media")
    t = _texto(ps)
    assert "Os presentes autos tratam da aquisição de água fictícia, conforme DFD (00000001)." in t
    assert "Relatório Banco de Preços (00000002)" in t and "arts. 4º e 5º, inciso II, da IN SEGES/ME nº 65/2021" in t
    assert "foi a Média Aritmética dos preços obtidos" in t
    assert ("estimada em R$ 18.000,00 (dezoito mil reais), enquadrando-se na hipótese de Dispensa de Licitação, nos "
            "termos do art. 75, inciso II, da Lei nº 14.133/2021") in t
    assert "20% da Seguridade Social é de R$ 3.600,00 (três mil e seiscentos reais)" in t
    assert "destinada exclusivamente para ME/EPP" in t and "§ 6º do art. 82" in t
    assert "não foram identificadas aquisições ou serviços com características semelhantes" in t
    assert "[informar" not in t


def test_dispensa_com_soma_do_pca_e_contratacao_ja_feita():
    _, ps = _gerar("servico", [Item("Limpeza", D("11949.30"))],
                   [Demanda("limpeza (PCA)", "PCA", D("13000")),
                    Demanda("limpeza do 1º semestre", "Nota de Empenho 2026NE000001", D("7876"), ja_contratada=True)],
                   objeto="contratação de limpeza fictícia", doc_referencia="DFD (1)", relatorio="2")
    t = _texto(ps)
    assert "foram identificadas as seguintes demandas semelhantes, observado o regramento do art. 4º" in t
    assert "Também, já foi realizada a contratação de limpeza do 1º semestre, no valor total de R$ 7.876,00" in t
    assert ("a soma total dos valores em questão, R$ 32.825,30 (trinta e dois mil oitocentos e vinte e cinco reais e "
            "trinta centavos), não ultrapassa o limite legal para dispensa de licitação, atualmente de R$ 65.492,11, "
            "conforme o Decreto nº 12.807/2025") in t
    tabela = next(p for p in ps if p.tipo == "tabela")
    assert tabela.linhas == [["Demanda", "Origem", "Desembolso 2026 (R$)"], ["limpeza (PCA)", "PCA", "13.000,00"]]


def test_fracionamento_vira_pregao_com_justificativa():
    e, ps = _gerar("bem", [Item("Material", D("40000"))], [Demanda("mesmo PDM", "PCA", D("30000"))],
                   objeto="aquisição de material fictício", doc_referencia="ETP (1)", relatorio="2", ref_comum="item D do ETP (1)")
    t = _texto(ps)
    assert e.modalidade == "pregao"
    assert "ultrapassa o limite legal para dispensa de licitação" in t and "mediante licitação" in t
    assert "modalidade Pregão Eletrônico, nos termos do art. 6º, inciso XLI" in t
    assert "como o valor estimado não ultrapassou o valor de R$ 80.000,00, a licitação será destinada exclusivamente" in t
    assert "Seguridade" not in t


def test_pregao_por_valor_sem_paragrafo_do_pca_e_me_epp_mista():
    _, ps = _gerar("bem", [Item("Blindado", D("483970")), Item("SUV", D("55000"))],
                   objeto="aquisição de veículos fictícios", doc_referencia="ETP (1)", relatorio="2")
    t = _texto(ps)
    assert "PCA" not in t and "conforme discriminado abaixo" in t
    assert "o item SUV, por não ultrapassar o valor de R$ 80.000,00, será destinado exclusivamente" in t
    assert "o item Blindado, de valor superior a R$ 80.000,00 e natureza indivisível, será destinado à ampla participação" in t
    assert "[informar item do TR ou do ETP]" in t           # ref_comum não informada → pendência


def test_engenharia_pela_seeng_e_campos_faltando_em_amarelo():
    _, ps = _gerar("servico_engenharia", [Item("Locação de nobreak", D("203968.64"))], fonte="seeng",
                   base_seeng="contratacoes_similares", objeto="contratação de locação fictícia de nobreak")
    t = _texto(ps)
    assert t.split("\n")[1].startswith("Tratam os autos de contratação de locação fictícia de nobreak, conforme [informar")
    assert "elaborada pela SEENG - Seção de Engenharia" in t and "art. 23, § 2º, inciso III" in t
    assert "serviço comum de engenharia, assim a despesa fica enquadrada em pregão eletrônico" in t
    assert "a licitação será destinada à ampla participação" in t
    html = html_sei(ps)
    assert "Times New Roman" in html and "text-indent: 25mm" in html
    assert '<span style="background-color: #ffff00;">[informar' in html


def test_cota_reservada_no_texto():
    itens = [Item("1", D("2000")), Item("2", D("85000"), divisivel=True)]
    e = enquadrar("bem", itens, [], "2026", forcar_licitacao=True)
    t = _texto(montar(DadosInformacao(objeto="aquisição fictícia", doc_referencia="ETP (1)", relatorio="2", ref_comum="item D"), e, "bem", itens, []))
    assert "o item 2, de natureza divisível e valor superior a R$ 80.000,00, terá cota reservada de até 25%" in t
    assert "art. 48, inciso III, da LC nº 123/2006" in t
