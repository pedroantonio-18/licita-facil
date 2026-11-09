"""
Utilitários de texto para certidões: normalização, CNPJ e datas.

As certidões vêm de sites diferentes (Receita, Caixa, TST, TCU, tribunais,
secretarias de fazenda), cada um com seu jeito de escrever datas e números.
Tudo aqui é determinístico e sem internet.
"""

import re
import unicodedata
from datetime import date

CNPJ_PATTERN = re.compile(r"(?<!\d)(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})(?!\d)")

DATA_NUMERICA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
# "de" depois do dia é opcional: a certidão estadual de Goiás imprime "4 NOVEMBRO DE 2026".
DATA_EXTENSO = re.compile(r"(\d{1,2})\s+(?:de\s+)?(" + "|".join(MESES) + r")\s+de\s+(\d{4})")

# Padrão comum a qualquer data, para usar dentro de outras expressões
DATA = r"(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+(?:de\s+)?(?:" + "|".join(MESES) + r")\s+de\s+\d{4})"


def normalizar(texto: str) -> str:
    """
    Minúsculas, sem acentos e com espaços simples — base para todas as buscas.

    NFKD também desfaz ligaduras tipográficas: PDFs salvos pela impressão do
    navegador (ex.: CRF da Caixa) trazem "Certiﬁcado" com "ﬁ" num caractere só.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.lower().split())


def apenas_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cnpj_valido(cnpj: str) -> bool:
    d = apenas_digitos(cnpj)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for pesos, pos in (([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], 12), ([6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], 13)):
        resto = sum(int(x) * p for x, p in zip(d[:pos], pesos)) % 11
        if (0 if resto < 2 else 11 - resto) != int(d[pos]):
            return False
    return True


def formatar_cnpj(cnpj: str) -> str:
    d = apenas_digitos(cnpj)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else cnpj


def cnpjs_no_texto(texto: str) -> list[str]:
    """CNPJs válidos, na ordem em que aparecem, sem repetição."""
    vistos: list[str] = []
    for m in CNPJ_PATTERN.finditer(texto or ""):
        d = apenas_digitos(m.group(1))
        if cnpj_valido(d) and d not in vistos:
            vistos.append(d)
    return vistos


CPF_PATTERN = re.compile(r"(?<!\d)(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d)")


def cpf_valido(cpf: str) -> bool:
    d = apenas_digitos(cpf)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for pos in (9, 10):
        soma = sum(int(x) * (pos + 1 - i) for i, x in enumerate(d[:pos]))
        if (soma * 10 % 11) % 10 != int(d[pos]):
            return False
    return True


def cpfs_no_texto(texto: str) -> list[str]:
    """CPFs válidos (formatados ou só dígitos), sem repetição — usados nas certidões de pessoa física."""
    vistos: list[str] = []
    for m in CPF_PATTERN.finditer(texto or ""):
        d = apenas_digitos(m.group(1))
        if cpf_valido(d) and d not in vistos:
            vistos.append(d)
    return vistos


def para_data(trecho: str) -> date | None:
    """Converte "15/04/2027" ou "15 de abril de 2027" em date."""
    t = normalizar(trecho)
    m = DATA_NUMERICA.search(t)
    if m:
        dia, mes, ano = (int(x) for x in m.groups())
    else:
        m = DATA_EXTENSO.search(t)
        if not m:
            return None
        dia, mes, ano = int(m.group(1)), MESES[m.group(2)], int(m.group(3))
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def primeira_data_apos(texto_normalizado: str, rotulo: str) -> date | None:
    """Primeira data que aparece logo depois de um rótulo (ex.: "valida ate")."""
    m = re.search(rotulo + r"[^0-9]{0,40}?" + DATA, texto_normalizado)
    return para_data(m.group(1)) if m else None
