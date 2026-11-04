"""
Orquestra a leitura e a conferência das certidões de uma empresa.
"""

import hashlib
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from app.certidoes import ROTULO_RESULTADO, ler_pdf
from app.conferencia import (
    PADRAO_OBRIGATORIAS, ItemChecklist, Parametros, aplicar_conferencias_manuais, conferir_certidao,
    montar_checklist, situacao_geral,
)


def textos_pdf(caminho: Path) -> list[str]:
    with fitz.open(caminho) as doc:
        return [pagina.get_text() for pagina in doc]


def analisar_empresa(pasta: Path, cnpj: str, p: Parametros, manuais: dict | None = None) -> list[ItemChecklist]:
    conferencias = []
    for arquivo in sorted(pasta.glob("*.pdf")):
        for certidao in ler_pdf(textos_pdf(arquivo), arquivo.name):
            conferencias.append(conferir_certidao(certidao, cnpj, p))
    itens = montar_checklist(conferencias, p)
    aplicar_conferencias_manuais(itens, manuais or {})
    return itens


def arquivos_recebidos(pasta: Path) -> list[dict]:
    """Nome, páginas e SHA-256 de cada arquivo recebido — para provar o que foi conferido."""
    lista = []
    for arquivo in sorted(pasta.glob("*.pdf")):
        conteudo = arquivo.read_bytes()
        with fitz.open(stream=conteudo, filetype="pdf") as doc:
            paginas = len(doc)
        lista.append({"arquivo": arquivo.name, "paginas": paginas, "sha256": hashlib.sha256(conteudo).hexdigest()})
    return lista


def parametros(meta: dict) -> Parametros:
    return Parametros(
        data_referencia=date.fromisoformat(meta["data_referencia"]),
        obrigatorias=meta.get("obrigatorias") or list(PADRAO_OBRIGATORIAS),
        dias_consultas=int(meta.get("dias_consultas", 30)),
        dias_falencia=int(meta.get("dias_falencia", 30)),
        objeto=meta.get("objeto", "compras"),
    )


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def serializar(nome: str, cnpj: str, itens: list[ItemChecklist]) -> dict:
    return {
        "nome": nome,
        "cnpj": cnpj,
        "situacao": situacao_geral(itens),
        "itens": [
            {
                "tipo": i.tipo,
                "tipo_nome": i.tipo_nome,
                "obrigatoria": i.obrigatoria,
                "situacao": i.situacao,
                "bloco": i.bloco,
                "fonte": i.fonte,
                "emissao": _iso(i.emissao),
                "validade": _iso(i.validade),
                "resultado": i.resultado,
                "situacao_automatica": i.situacao_automatica,
                "conferencia_manual": i.conferencia_manual,
                "observacoes": i.observacoes,
                "documentos": [
                    {
                        "tipo": c.certidao.tipo,
                        "arquivo": c.certidao.arquivo,
                        "paginas": c.certidao.paginas,
                        "emissao": _iso(c.certidao.emissao),
                        "validade_fim": _iso(c.certidao.validade_fim),
                        "validade_origem": c.certidao.validade_origem,
                        "resultado": c.certidao.resultado,
                        "resultado_rotulo": ROTULO_RESULTADO.get(c.certidao.resultado, ""),
                        "detalhes": c.certidao.detalhes,
                        "situacao": c.situacao,
                        "observacoes": c.observacoes,
                    }
                    for c in i.conferencias
                ],
            }
            for i in itens
        ],
    }
