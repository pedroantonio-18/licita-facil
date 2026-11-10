"""
Valores por extenso, no padrão usado nas Informações da SJGO:
"R$ 2.028,73 (dois mil e vinte e oito reais e setenta e três centavos)",
"R$ 739.645,71 (setecentos e trinta e nove mil seiscentos e quarenta e cinco reais e
setenta e um centavos)", "R$ 18.000,00 (dezoito mil reais)".

Regra do "e" entre grupos (mil, milhão): só antes do último grupo quando ele é menor que
cem ou é centena redonda ("dois mil e vinte", "três mil e seiscentos", mas "dez mil cento
e quarenta e três").
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
            "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete",
            "dezoito", "dezenove"]
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
            "setecentos", "oitocentos", "novecentos"]
ESCALAS = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões")]


def _ate_999(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    partes = [CENTENAS[c]] if c else []
    if resto:
        if resto < 20:
            partes.append(UNIDADES[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(DEZENAS[d] + (f" e {UNIDADES[u]}" if u else ""))
    return " e ".join(partes)


def inteiro_por_extenso(n: int) -> str:
    """Número inteiro por extenso ("5" → "cinco", "1001" → "mil e um")."""
    if n < 0:
        raise ValueError("Valor negativo")
    if n == 0:
        return "zero"
    grupos = []
    while n:
        n, g = divmod(n, 1000)
        grupos.append(g)
    partes: list[tuple[int, str]] = []          # (valor do grupo, texto)
    for i in range(len(grupos) - 1, -1, -1):
        g = grupos[i]
        if not g:
            continue
        if i == 1 and g == 1:
            texto = "mil"                          # "mil", não "um mil"
        else:
            singular, plural = ESCALAS[i]
            texto = _ate_999(g) + (f" {singular if g == 1 else plural}" if i else "")
        partes.append((g, texto))
    saida = partes[0][1]
    for idx, (g, texto) in enumerate(partes[1:], start=1):
        ultimo = idx == len(partes) - 1
        junta = ultimo and (g < 100 or g % 100 == 0)
        saida += (" e " if junta else " ") + texto
    return saida


def _moeda_inteira(reais: int) -> str:
    if reais == 0:
        return ""
    texto = inteiro_por_extenso(reais)
    if reais == 1:
        return "um real"
    # "um milhão de reais", "dois milhões de reais"; mas "um milhão e cem reais"
    if reais % 1_000_000 == 0:
        return f"{texto} de reais"
    return f"{texto} reais"


def reais_por_extenso(valor) -> str:
    """Valor em reais por extenso: Decimal("2028.73") → "dois mil e vinte e oito reais e setenta e três centavos"."""
    v = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if v < 0:
        raise ValueError("Valor negativo")
    reais = int(v)
    centavos = int((v - reais) * 100)
    partes = []
    if reais:
        partes.append(_moeda_inteira(reais))
    if centavos:
        partes.append(f"{inteiro_por_extenso(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    if not partes:
        return "zero real"
    return " e ".join(partes)


def formatar_reais(valor) -> str:
    """Decimal("81254.74") → "81.254,74"."""
    v = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    inteiro, dec = f"{v:.2f}".split(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return ".".join(grupos) + "," + dec


def ler_reais(texto: str) -> Decimal:
    """"81.254,74" / "R$ 81.254,74" / "81254.74" → Decimal."""
    t = str(texto).replace("R$", "").replace(" ", "").strip()
    if not t:
        raise ValueError("Valor vazio")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return Decimal(t).quantize(Decimal("0.01"))


def valor_com_extenso(valor) -> str:
    """"R$ 81.254,74 (oitenta e um mil duzentos e cinquenta e quatro reais e setenta e quatro centavos)"."""
    return f"R$ {formatar_reais(valor)} ({reais_por_extenso(valor)})"
