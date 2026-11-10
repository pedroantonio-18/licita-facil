from decimal import Decimal as D

import pytest

from app.regras import Demanda, Item, enquadrar


def test_dispensa_dentro_do_limite_com_seguridade():
    e = enquadrar("bem", [Item("Água mineral", D("18000.00"))], [], "2026")
    assert e.modalidade == "dispensa" and e.inciso == "II" and e.limite == D("65492.11")
    assert e.seguridade == D("3600.00") and e.fracionamento_ok and e.me_epp["regra"] == "exclusiva"


def test_soma_com_pca_e_ja_contratado():
    # caso como o da limpeza do terreno: 11.949,30 + demanda do PCA + 7.876,00 já empenhado
    e = enquadrar("servico", [Item("Limpeza 2º semestre", D("11949.30"))],
                  [Demanda("Limpeza (PCA)", "PCA", D("13000.00")),
                   Demanda("Limpeza 1º semestre", "Nota de Empenho", D("7876.00"), ja_contratada=True)], "2026")
    assert e.soma_exercicio == D("32825.30") and e.modalidade == "dispensa"


def test_fracionamento_obriga_licitacao():
    e = enquadrar("bem", [Item("Material", D("40000"))], [Demanda("Mesmo PDM no PCA", "PCA", D("30000"))], "2026")
    assert not e.fracionamento_ok and e.modalidade == "pregao" and e.seguridade is None
    assert any("Somadas as demandas" in a for a in e.avisos)
    propria = enquadrar("bem", [Item("Água", D("18000"))], [Demanda("SETMAT_0005", "PCA", D("18000"), propria=True)], "2026")
    assert propria.soma_exercicio == D("18000")      # a própria demanda no PCA não soma duas vezes


def test_engenharia_usa_inciso_i_e_dispensa_e_sempre_exclusiva():
    e = enquadrar("servico_engenharia", [Item("Projeto", D("81254.74"))], [], "2026")
    assert e.inciso == "I" and e.modalidade == "dispensa" and e.limite == D("130984.20")
    assert e.avisos == [] and e.limite_confirmado
    assert e.me_epp["regra"] == "exclusiva"      # dispensa por valor: exclusiva mesmo acima de R$ 80 mil


def test_me_epp_mista_e_forcar_licitacao():
    e = enquadrar("bem", [Item("Veículo blindado", D("483970")), Item("SUV", D("55000"))], [], "2026")
    assert e.modalidade == "pregao" and e.me_epp["regra"] == "mista"
    assert e.me_epp["exclusivos"] == ["SUV"] and e.me_epp["amplos"] == ["Veículo blindado"]
    assert enquadrar("bem", [Item("x", D("1000"))], [], "2026", forcar_licitacao=True).modalidade == "pregao"


def test_obra_acima_do_limite_e_erros():
    assert enquadrar("obra", [Item("Reforma", D("500000"))], [], "2026").modalidade == "concorrencia"
    with pytest.raises(ValueError):
        enquadrar("bem", [], [], "2026")
    with pytest.raises(ValueError):
        enquadrar("bem", [Item("x", D("1"))], [], "1999")
    proximo = enquadrar("bem", [Item("x", D("1000"))], [], "2027")     # decreto do ano ainda não publicado
    assert proximo.limite == D("65492.11") and any("ainda não cadastrado" in a for a in proximo.avisos)


def _exemplo_selit(divisivel, **kw):
    itens = [Item(f"{n}", D("2000")) for n in range(1, 10)] + [Item("10", D("85000"), divisivel=divisivel)]
    return enquadrar(kw.pop("natureza", "bem"), itens, [], "2026", **kw)


def test_exemplo_da_selit_item_divisivel_tem_cota_reservada():
    e = _exemplo_selit(True)
    assert e.modalidade == "pregao" and e.valor_estimado == D("103000")
    assert e.me_epp["exclusivos"] == [str(n) for n in range(1, 10)] and e.me_epp["cotas"] == ["10"] and e.me_epp["amplos"] == []
    assert e.me_epp["regra"] == "mista" and any("Cota reservada" in a for a in e.avisos)


def test_exemplo_da_selit_item_indivisivel_vai_para_ampla():
    e = _exemplo_selit(False)
    assert e.me_epp["amplos"] == ["10"] and e.me_epp["cotas"] == [] and len(e.me_epp["exclusivos"]) == 9


def test_exemplo_da_selit_grupo_unico_conta_o_valor_do_grupo():
    e = _exemplo_selit(True, grupo_unico=True)
    assert e.me_epp["exclusivos"] == [] and len(e.me_epp["amplos"]) == 10 and e.me_epp["regra"] == "ampla"
    assert any("Grupo único" in a for a in e.avisos)


def test_exemplo_da_selit_engenharia_cabe_em_dispensa_e_tudo_e_exclusivo():
    e = _exemplo_selit(True, natureza="servico_engenharia")
    assert e.modalidade == "dispensa" and e.inciso == "I" and len(e.me_epp["exclusivos"]) == 10 and e.me_epp["cotas"] == []


def test_item_acima_de_4_8_milhoes_nao_tem_tratamento_favorecido():
    e = enquadrar("bem", [Item("Grande", D("5000000"), divisivel=True)], [], "2026")
    assert e.me_epp["sem_beneficio"] == ["Grande"] and e.me_epp["cotas"] == [] and e.me_epp["regra"] == "ampla"
