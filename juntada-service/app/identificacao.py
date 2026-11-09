"""
Sugere razão social e CNPJ da empresa a partir das certidões anexadas.

As certidões trazem o CNPJ da empresa e, em geral, a razão social logo ao
lado ("Razão Social:", "Nome:"). É só uma sugestão para o servidor conferir.
"""

import re
from collections import Counter

from app.texto import cnpjs_no_texto, formatar_cnpj

# "Requerente" é o rótulo da certidão de falência do TJGO
_ROTULO_NOME = re.compile(r"(?:raz[ãa]o social|nome empresarial|nome|requerente)\s*:\s*([^\n]{3,150})", re.IGNORECASE)
# Sufixo logo após vírgula é lista, não razão social: "Falência de Empresários, Sociedades Empresariais, ME e EPP"
_SUFIXO = re.compile(r"([A-ZÀ-Ý0-9][A-ZÀ-Ý0-9&.,'\- ]{2,140}?(?<!,)\s(?:LTDA\.?|EIRELI|S\.?\s?A\.?|S/A|LIMITADA|ME|EPP))(?![A-Za-zÀ-ý])")


# Empresa do carimbo de assinatura digital ("v3.0 - <CERTIFICADORA> Blockchain Documentos Digitais e Serviços LTDA")
# aparece em todas as páginas, mas nunca é a licitante.
_CERTIFICADORA = re.compile(r"BLOCKCHAIN|DOCUMENTOS DIGITAIS|CERTIFICA[CÇ][AÃ]O DIGITAL|AUTORIDADE CERTIFICADORA")


def _limpar_prefixo(nome: str) -> str:
    """Tira o texto que vem antes da razão social nos termos de registro da Junta:
    "CERTIFICO QUE ESTE DOCUMENTO DA EMPRESA X LTDA" → "X LTDA"; "2023 DA EMPRESA X LTDA" → "X LTDA"."""
    m = list(re.finditer(r"\b(?:DA|DE|A) EMPRESA\s+", nome))
    if m:
        nome = nome[m[-1].end():]
    return re.sub(r"^(?:\S*\d\S*\s+(?:-\s+)?)+", "", nome)


def identificar(textos: list[str]) -> dict:
    contagem: Counter[str] = Counter()
    candidatos: list[tuple[str, int, str, int]] = []   # (nome, peso, texto em maiúsculas, posição)
    for texto in textos:
        contagem.update(cnpjs_no_texto(texto))
        maiusculo = texto.upper()
        for m in _ROTULO_NOME.finditer(texto):
            nome = " ".join(m.group(1).split()).strip(" .,-")
            if len(nome.split()) >= 2 and not re.search(r"\d{3}", nome):
                candidatos.append((nome.upper(), 2, maiusculo, m.start()))
        for m in _SUFIXO.finditer(maiusculo):
            nome = _limpar_prefixo(" ".join(m.group(1).split()))
            if len(nome.split()) >= 2:
                candidatos.append((nome, 1, maiusculo, m.start()))

    if not contagem:
        return {"cnpj": None, "cnpj_formatado": None, "razao_social": None}
    cnpj = max(contagem, key=lambda c: (contagem[c], c[8:12] == "0001"))

    # Contratos citam outras empresas (sócia, certificadora da assinatura digital): vale mais
    # o nome que aparece perto do CNPJ da própria empresa.
    formas = (cnpj, formatar_cnpj(cnpj))
    nomes: Counter[str] = Counter()
    for nome, peso, texto, pos in candidatos:
        perto = any(0 <= texto.find(f, max(0, pos - 300)) <= pos + 300 + len(nome) for f in formas)
        if not _CERTIFICADORA.search(nome):
            nomes[nome] += peso + (3 if perto else 0)
    razao = max(nomes, key=lambda n: (nomes[n], len(n))) if nomes else None
    return {"cnpj": cnpj, "cnpj_formatado": formatar_cnpj(cnpj), "razao_social": razao}
