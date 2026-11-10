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
    # sobra de número antes do nome ("0001-81 ALFA LTDA", "2023 DA EMPRESA …" já tratado acima)
    nome = re.sub(r"^(?:\S*\d\S*\s+(?:-\s+)?)+", "", nome).strip(" ,.-:")
    return nome


# O CNPJ do contador/escritório de contabilidade costuma vir no rodapé de toda página
# ("Elaborado por: … CONTÁBIL LTDA - CNPJ …") e ganharia por frequência.
_CONTEXTO_CONTADOR = re.compile(r"CONTAB|CONTADOR|CONT[ÁA]BIL|\bCRC\b|ELABORADO POR|ESCRIT[ÓO]RIO", re.IGNORECASE)
# Contextos em que o CNPJ é o da própria empresa
_CONTEXTO_EMPRESA = re.compile(
    r"FORNECEDOR\s+CNPJ|INSCRIT[AO]\s+NO\s+CNPJ|CNPJ\s+SOB\s+O\s+N|RAZ[ÃA]O\s+SOCIAL|NOME\s+EMPRESARIAL|"
    r"DENOMINA[ÇC][ÃA]O|OUTORGANTE|CONTRATANTE|N[ÚU]MERO DE INSCRI[ÇC][ÃA]O", re.IGNORECASE)


def _pontuacao(texto: str, posicoes: list[int]) -> int:
    """Pontos de um CNPJ: cada contexto diferente conta uma vez (rodapé repetido em toda página
    conta uma só), contexto de contador não conta, contexto típico da empresa vale mais."""
    pontos, vistos = 0, set()
    for pos in posicoes:
        antes = " ".join(texto[max(0, pos - 90):pos].split())
        if antes in vistos:
            continue
        vistos.add(antes)
        if _CONTEXTO_CONTADOR.search(antes[-60:]):
            continue
        pontos += 3 if _CONTEXTO_EMPRESA.search(antes[-60:]) else 1
    return pontos


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

    cnpj = max(ocorrencias, key=lambda c: (_pontuacao(texto, ocorrencias[c]), c[8:12] == "0001"))

    candidatos: Counter[str] = Counter()
    for pos in ocorrencias[cnpj]:
        trecho = texto[max(0, pos - _JANELA): pos + _JANELA]
        for m in _RAZAO_SOCIAL.finditer(trecho.upper()):
            nome = _limpar_nome(m.group(1))
            if len(nome.split()) >= 2 and not _CONTEXTO_CONTADOR.search(nome):   # escritório de contabilidade
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
