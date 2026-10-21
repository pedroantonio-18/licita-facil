"""
R07 (vínculo familiar) e R08 (endereço coincidente).

Cada regra tem casos que devem gerar achado e casos parecidos que não
devem — o custo de um falso positivo num relatório anexado ao SEI é alto.
"""

import pytest

from app.crossing.rules import (
    Empresa, cruzar_empresas, _nomes_equivalentes, _normalizar_endereco,
)


def empresa(nome, pessoas=(), enderecos=()):
    return Empresa(
        id=nome, nome=nome, cnpj_principal="0" * 14,
        cnpjs=[], cpfs=[], ceps=[], telefones=[],
        pessoas=[{"nome": "X Y", "funcao": "não identificada", **p} for p in pessoas],
        enderecos=[{"valor": e, "trecho": "sede"} for e in enderecos],
    )


def regras(a, b, codigo):
    return [x for x in cruzar_empresas([a, b]) if x.regra_codigo == codigo]


# ---------------------------------------------------------------------------
# Comparação de nomes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("x,y", [
    ("ANA PAULA MOREIRA LIMA", "Ana Paula Moreira Lima Duarte"),                     # nome de casada
    ("SÔNIA REGINA DE ARAÚJO FONTES", "Sonia Regina de Araujo Fontes"),               # acento/caixa
    ("LUCAS JOVE BRANDAO", "LUCAS JOYE BRANDAO"),                                        # erro de OCR
])
def test_nomes_equivalentes(x, y):
    assert _nomes_equivalentes(x, y)[0]


@pytest.mark.parametrize("x,y", [
    ("JOSE DA SILVA", "MARIA JOSE DA SILVA SANTOS"),          # prenome diferente
    ("JOSE SILVA", "JOSE ROBERTO SILVA"),                     # só 2 nomes: não basta estar contido
    ("ANA DA SILVA MELO", "ANA CAROLINA FARIAS DUARTE"),
    ("JOSÉ HENRIQUE BRAGA TEIXEIRA", "JOÃO HENRIQUE ABRÃO MOURA"),
    (None, "FULANO DE TAL"),
])
def test_nomes_nao_equivalentes(x, y):
    assert not _nomes_equivalentes(x, y)[0]


# ---------------------------------------------------------------------------
# R07 — vínculo familiar
# ---------------------------------------------------------------------------

def test_r07_conjuge_de_socio_de_a_e_procuradora_de_b():
    a = empresa("ALFA", [{"nome": "CARLOS ALBERTO MENDES", "funcao": "sócio", "conjuge": "JULIANA PRADO MENDES"}])
    b = empresa("BETA", [{"nome": "JULIANA PRADO MENDES", "funcao": "procuradora"}])
    achados = regras(a, b, "R07")
    assert len(achados) == 1
    assert achados[0].campo == "conjuge"
    assert achados[0].prioridade == "alta"
    assert "cônjuge informado: JULIANA PRADO MENDES" in achados[0].evidencia_a["trecho"]


def test_r07_casal_informado_dos_dois_lados_e_um_achado_so():
    a = empresa("ALFA", [{"nome": "RODRIGO ALMEIDA CASTRO", "conjuge": "FERNANDA LIMA CASTRO"}])
    b = empresa("BETA", [{"nome": "FERNANDA LIMA CASTRO", "conjuge": "RODRIGO ALMEIDA CASTRO"}])
    assert len(regras(a, b, "R07")) == 1


def test_r07_conjuge_com_sobrenome_de_casada():
    a = empresa("ALFA", [{"nome": "BRUNO FERREIRA DUARTE", "conjuge": "ANA PAULA MOREIRA LIMA"}])
    b = empresa("BETA", [{"nome": "ANA PAULA MOREIRA LIMA DUARTE", "funcao": "sócia"}])
    assert [x.campo for x in regras(a, b, "R07")] == ["conjuge"]


def test_r07_pai_de_um_e_socio_de_outra():
    a = empresa("ALFA", [{"nome": "JOAO HENRIQUE ABRAO MOURA", "filiacao_pai": "JOAO MAURICIO MARTINS MOURA"}])
    b = empresa("BETA", [{"nome": "JOÃO MAURÍCIO MARTINS MOURA", "funcao": "sócio administrador"}])
    achados = regras(a, b, "R07")
    assert [x.campo for x in achados] == ["filiacao"]
    assert "pai de JOAO HENRIQUE ABRAO MOURA" in achados[0].valor


def test_r07_irmaos_exige_pai_e_mae():
    pais = {"filiacao_pai": "RUBENS ALVES PEREIRA", "filiacao_mae": "ANA DA SILVA PEREIRA"}
    a = empresa("ALFA", [{"nome": "TIAGO ROBERTO ALVES PEREIRA", **pais}])
    b = empresa("BETA", [{"nome": "MARCELO ALVES PEREIRA", **pais}])
    assert [x.campo for x in regras(a, b, "R07")] == ["filiacao_comum"]

    so_mae = empresa("GAMA", [{"nome": "MARCELO ALVES PEREIRA", "filiacao_mae": "ANA DA SILVA PEREIRA"}])
    assert regras(a, so_mae, "R07") == []


def test_r07_mesma_pessoa_nao_e_irma_de_si_mesma():
    pais = {"filiacao_pai": "RUBENS ALVES PEREIRA", "filiacao_mae": "ANA DA SILVA PEREIRA"}
    a = empresa("ALFA", [{"nome": "TIAGO ROBERTO ALVES PEREIRA", **pais}])
    b = empresa("BETA", [{"nome": "TIAGO ROBERTO ALVES PEREIRA", **pais}])
    assert regras(a, b, "R07") == []          # é a R05 que aponta a mesma pessoa
    assert len(regras(a, b, "R05")) == 1


def test_r07_vinculo_interno_nao_e_achado():
    """Família dentro de uma mesma empresa não é vínculo entre licitantes."""
    a = empresa("ALFA", [
        {"nome": "EDSON MENDES FONTES", "conjuge": "SONIA REGINA DE ARAUJO FONTES"},
        {"nome": "SONIA REGINA DE ARAUJO FONTES", "conjuge": "EDSON MENDES FONTES"},
    ])
    b = empresa("BETA", [{"nome": "FULANO DE TAL SOUZA"}])
    assert regras(a, b, "R07") == []


# ---------------------------------------------------------------------------
# R08 — endereço coincidente
# ---------------------------------------------------------------------------

def test_normalizacao_de_endereco():
    palavras, numeros = _normalizar_endereco("R. T-33, nº 188, Apto. 1.004-B, Ed. Special Place, St. Bueno, CEP 74.215-140")
    assert numeros == {"33", "188", "1004"}
    assert palavras.startswith("RUA T APTO B EDIFICIO SPECIAL PLACE SETOR BUENO")


def test_r08_mesmo_endereco_com_abreviacoes_diferentes():
    a = empresa("ALFA", enderecos=["Rua das Acácias, nº 126, Qd. 72, Lt. 04, Sala 01, Loteamento Bela Vista, Rio Verde/GO"])
    b = empresa("BETA", [{"nome": "PEDRO ALVES COSTA", "funcao": "contador",
                          "endereco": "R. das Acacias, 126, Quadra 72, Lote 4, Lot. Bela Vista, Rio Verde - GO"}])
    achados = regras(a, b, "R08")
    assert len(achados) == 1
    assert achados[0].prioridade == "media"
    assert achados[0].evidencia_b["trecho"] == "Endereço de PEDRO ALVES COSTA"


def test_r08_mesmo_predio_salas_diferentes_coincide():
    """Mesmo número com sala a mais em um dos lados: aponta (a nota explica o caso de edifício comercial)."""
    a = empresa("ALFA", enderecos=["Avenida Central, nº 2651, Setor Oeste, Goiânia-GO"])
    b = empresa("BETA", enderecos=["Av. Central, 2651, Sala 03, Setor Oeste, Goiânia-GO"])
    assert len(regras(a, b, "R08")) == 1


@pytest.mark.parametrize("ea,eb", [
    ("Rua T-33, nº 188, Setor Bueno, Goiânia-GO", "Rua T-33, nº 190, Setor Bueno, Goiânia-GO"),              # outro número
    ("Rua T-33, nº 188, Setor Bueno, Goiânia-GO", "Avenida São Francisco, nº 188, Santa Genoveva, Goiânia-GO"),  # outra rua, mesmo número
    ("Rua T-33, nº 188, Setor Bueno, Goiânia-GO", "Rua T-30, nº 188, Setor Bueno, Goiânia-GO"),              # outra rua T
    ("Centro, Ceres-GO", "Centro, Ceres-GO"),                                                               # sem número: genérico demais
])
def test_r08_enderecos_diferentes_nao_coincidem(ea, eb):
    assert regras(empresa("ALFA", enderecos=[ea]), empresa("BETA", enderecos=[eb]), "R08") == []
