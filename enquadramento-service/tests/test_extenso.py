from decimal import Decimal

import pytest

from app.extenso import formatar_reais, inteiro_por_extenso, ler_reais, reais_por_extenso, valor_com_extenso

# Gabarito: valores por extenso como escritos nas Informações já assinadas pela SJGO
CASOS_SJGO = [
    ("739645.71", "setecentos e trinta e nove mil seiscentos e quarenta e cinco reais e setenta e um centavos"),
    ("203968.64", "duzentos e três mil novecentos e sessenta e oito reais e sessenta e quatro centavos"),
    ("10143.67", "dez mil cento e quarenta e três reais e sessenta e sete centavos"),
    ("2028.73", "dois mil e vinte e oito reais e setenta e três centavos"),
    ("11949.30", "onze mil novecentos e quarenta e nove reais e trinta centavos"),
    ("2389.86", "dois mil trezentos e oitenta e nove reais e oitenta e seis centavos"),
    ("232247.10", "duzentos e trinta e dois mil duzentos e quarenta e sete reais e dez centavos"),
    ("3620.04", "três mil seiscentos e vinte reais e quatro centavos"),
    ("724.00", "setecentos e vinte e quatro reais"),
    ("18000.00", "dezoito mil reais"),
    ("3600.00", "três mil e seiscentos reais"),
    ("32825.30", "trinta e dois mil oitocentos e vinte e cinco reais e trinta centavos"),
    ("7876.00", "sete mil oitocentos e setenta e seis reais"),
    ("4320.00", "quatro mil trezentos e vinte reais"),
    ("8575.55", "oito mil quinhentos e setenta e cinco reais e cinquenta e cinco centavos"),
]


@pytest.mark.parametrize("valor,esperado", CASOS_SJGO)
def test_extenso_igual_as_informacoes_da_sjgo(valor, esperado):
    assert reais_por_extenso(Decimal(valor)) == esperado


@pytest.mark.parametrize("valor,esperado", [
    ("0.01", "um centavo"), ("1", "um real"), ("1.01", "um real e um centavo"), ("100", "cem reais"),
    ("101", "cento e um reais"), ("1000", "mil reais"), ("1001", "mil e um reais"), ("1100", "mil e cem reais"),
    ("1250", "mil duzentos e cinquenta reais"), ("21000", "vinte e um mil reais"), ("100000", "cem mil reais"),
    ("1000000", "um milhão de reais"), ("2000000", "dois milhões de reais"), ("1000100", "um milhão e cem reais"),
    ("1234567.89", "um milhão duzentos e trinta e quatro mil quinhentos e sessenta e sete reais e oitenta e nove centavos"),
    ("0", "zero real"),
])
def test_extenso_casos_gerais(valor, esperado):
    assert reais_por_extenso(Decimal(valor)) == esperado


def test_inteiros_formatacao_e_leitura():
    assert inteiro_por_extenso(5) == "cinco" and inteiro_por_extenso(60) == "sessenta"
    assert formatar_reais(Decimal("81254.74")) == "81.254,74" and formatar_reais(Decimal("65492.11")) == "65.492,11"
    assert formatar_reais(Decimal("5")) == "5,00" and formatar_reais(Decimal("1234567.8")) == "1.234.567,80"
    assert ler_reais("R$ 81.254,74") == Decimal("81254.74") == ler_reais("81254.74")
    assert valor_com_extenso(Decimal("18000")) == "R$ 18.000,00 (dezoito mil reais)"
    with pytest.raises(ValueError):
        ler_reais("")
