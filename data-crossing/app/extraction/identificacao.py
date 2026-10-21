"""
Identificação da empresa principal de um conjunto de PDFs.

Usada para preencher razão social e CNPJ na tela assim que os arquivos
são anexados. Roda localmente, sem internet e sem LLM:

- CNPJ: o CNPJ válido mais frequente no texto, preferindo matriz (/0001)
  e ignorando órgãos de registro (ex.: JUCEG).
- Razão social: o nome terminado em LTDA, EIRELI, S/A etc. que mais
  aparece perto das ocorrências desse CNPJ.

É uma sugestão para o servidor conferir, não um dado do cruzamento.
"""

import re
from collections import Counter

from app.crossing.rules import cnpjs_ignorados
from app.extraction.patterns import CNPJ_PATTERN, cnpj_valido, format_cnpj, normalize_cnpj

_JANELA = 400

_RAZAO_SOCIAL = re.compile(
    r"([A-ZÀ-Ý0-9][A-ZÀ-Ý0-9&.,'\- ]{2,140}?\s"
    r"(?:LTDA\.?|EIRELI|S\.\s?A\.?|S/A|LIMITADA))(?![A-Za-zÀ-ý])"
)

# Palavras que costumam preceder o nome sem fazer parte dele
_PREFIXOS = re.compile(
    r"^(?:.*?\b(?:EMPRESA|SOCIEDADE|DENOMINADA|DENOMINA[ÇC][ÃA]O|RAZ[ÃA]O SOCIAL|NOME EMPRESARIAL|"
    r"OUTORGANTE|CONCESSION[ÁA]RIO|CONTRATADA|ATO DA EMPRESA|CONTRATO SOCIAL|"
    r"ALTERA[ÇC][ÃA]O CONTRATUAL|CONSOLIDA[ÇC][ÃA]O|CERTID[ÃA]O)\b[:\s-]*(?:D[AEO]\s+)?)",
)


def _limpar_nome(nome: str) -> str:
    nome = " ".join(nome.split()).strip(" ,.-")
    nome = _PREFIXOS.sub("", nome).strip(" ,.-:")
    return nome


def identificar_empresa(textos: list[str]) -> dict:
    """
    Args:
        textos: texto de cada página (ou documento)

    Returns:
        {"cnpj": "14 dígitos" | None, "cnpj_formatado", "razao_social": str | None,
         "ocorrencias_cnpj": int}
    """
    texto = "\n".join(textos)
    ignorados = cnpjs_ignorados()

    ocorrencias: dict[str, list[int]] = {}
    for m in CNPJ_PATTERN.finditer(texto):
        n = normalize_cnpj(m.group(1))
        if n in ignorados or not cnpj_valido(n):
            continue
        ocorrencias.setdefault(n, []).append(m.start())

    if not ocorrencias:
        return {"cnpj": None, "cnpj_formatado": None, "razao_social": None, "ocorrencias_cnpj": 0}

    # Mais frequente; em empate, a matriz (/0001)
    cnpj = max(ocorrencias, key=lambda c: (len(ocorrencias[c]), c[8:12] == "0001"))

    candidatos: Counter[str] = Counter()
    for pos in ocorrencias[cnpj]:
        trecho = texto[max(0, pos - _JANELA): pos + _JANELA]
        for m in _RAZAO_SOCIAL.finditer(trecho.upper()):
            nome = _limpar_nome(m.group(1))
            if len(nome.split()) >= 2:
                candidatos[nome] += 1

    razao = None
    if candidatos:
        # Mais frequente; em empate, o mais longo (forma completa do nome)
        razao = max(candidatos, key=lambda n: (candidatos[n], len(n)))

    return {
        "cnpj": cnpj,
        "cnpj_formatado": format_cnpj(cnpj),
        "razao_social": razao,
        "ocorrencias_cnpj": len(ocorrencias[cnpj]),
    }
