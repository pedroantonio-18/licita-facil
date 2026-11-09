"""
Endpoints das minutas (aviso de dispensa e edital de pregão a partir dos modelos da AGU).

Sem estado: a tela manda o modelo escolhido, o formulário e as decisões, e recebe a
minuta montada. Nada do processo fica guardado no servidor.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.ia import montar_prompt, pendencias_para_ia, validar
from app.modelo import NOMES_TEMAS, Modelo, ler_modelo, numerar
from app.montagem import Decisoes, Minuta, montar
from app.preenchimento import DADOS_JF, DadosCaso, preencher
from app.saida_sei import html_sei

log = logging.getLogger(__name__)
router = APIRouter(prefix="/minutas", tags=["Minutas"])

MODELOS_DIR = Path(os.environ.get("MINUTAS_MODELOS_DIR", Path(__file__).resolve().parent.parent / "modelos"))
TAMANHO_MAXIMO = 20 * 1024 * 1024

TIPOS = {"aviso_dispensa": "Aviso de Contratação Direta (dispensa eletrônica)",
         "edital_pregao": "Edital de Pregão Eletrônico"}


# ---------------------------------------------------------------------------
# Modelos disponíveis
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _ler(caminho: str, modificado: float) -> Modelo:
    return ler_modelo(caminho)


def _modelos() -> dict[str, tuple[Path, Modelo]]:
    saida = {}
    for arquivo in sorted(MODELOS_DIR.glob("*.docx")):
        try:
            m = _ler(str(arquivo), arquivo.stat().st_mtime)
        except Exception:                                    # arquivo corrompido não derruba a lista
            log.exception("Modelo ilegível: %s", arquivo.name)
            continue
        if m.tipo in TIPOS:
            saida[arquivo.stem] = (arquivo, m)
    return saida


def _modelo(modelo_id: str) -> Modelo:
    modelos = _modelos()
    if modelo_id not in modelos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo não encontrado.")
    return modelos[modelo_id][1]


def _info(modelo_id: str, m: Modelo) -> dict:
    return {"id": modelo_id, "tipo": m.tipo, "tipo_nome": TIPOS[m.tipo], "versao": m.versao,
            "temas": sorted({t for b in m.blocos for t in b.temas})}


@router.get("/config")
async def config():
    return {"dados_jf": DADOS_JF, "temas": NOMES_TEMAS, "tipos": TIPOS,
            "modelos": [_info(i, m) for i, (_, m) in _modelos().items()]}


@router.post("/modelos")
async def enviar_modelo(arquivo: UploadFile = File(...)):
    """Nova versão de modelo da AGU (.docx). Fica ao lado das anteriores."""
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Arquivo passa de 20 MB.")
    try:
        m = ler_modelo(conteudo)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não foi possível ler o arquivo como .docx.")
    if m.tipo not in TIPOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "O arquivo não parece um modelo da AGU de aviso de dispensa ou edital de pregão.")
    versao = re.sub(r"[^A-Za-z0-9]+", "-", m.versao or "sem-versao").strip("-")
    destino = MODELOS_DIR / f"{m.tipo.replace('_', '-')}-agu-{versao}.docx"
    MODELOS_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)
    return _info(destino.stem, m)


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------

class DecisoesEntrada(BaseModel):
    remover: dict[str, str] = Field(default_factory=dict)
    textos: dict[str, str] = Field(default_factory=dict)
    campos: dict[str, str] = Field(default_factory=dict)
    manter: list[str] = Field(default_factory=list)
    motivos: dict[str, str] = Field(default_factory=dict)
    origem: dict[str, str] = Field(default_factory=dict)


class PedidoMontagem(BaseModel):
    modelo_id: str
    dados: dict = Field(default_factory=dict)
    temas: list[str] = Field(default_factory=list)
    decisoes: DecisoesEntrada = Field(default_factory=DecisoesEntrada)


def _dados(entrada: dict) -> DadosCaso:
    validos = {k: v for k, v in entrada.items() if k in DadosCaso.__dataclass_fields__}
    for k, v in list(validos.items()):
        if k != "sites" and not isinstance(v, str):
            validos[k] = str(v)
    return DadosCaso(**validos)


def _decisoes(m: Modelo, pedido: PedidoMontagem) -> Decisoes:
    temas = {t for t in pedido.temas if t in NOMES_TEMAS}
    base = preencher(m, _dados(pedido.dados), temas)
    ids = {b.id for b in m.blocos}
    campos = {c.id for b in m.blocos for c in b.campos}
    e = pedido.decisoes
    extra = Decisoes(
        temas=temas,
        remover={k: v for k, v in e.remover.items() if k in ids},
        textos={k: v for k, v in e.textos.items() if k in ids},
        campos={k: v for k, v in e.campos.items() if k in campos},
        manter={k for k in e.manter if k in ids},
        motivos={k: v for k, v in e.motivos.items() if k in ids or k in campos},
        origem={k: v for k, v in e.origem.items() if k in ids or k in campos},
    )
    return base.juntar(extra)


def _serializar(m: Modelo, mi: Minuta) -> dict:
    notas = {b.id: b.notas for b in m.blocos if b.notas}
    campos = {b.id: [asdict(c) for c in b.campos] for b in m.blocos if b.campos}
    return {
        "modelo": {"tipo": m.tipo, "tipo_nome": TIPOS.get(m.tipo, ""), "versao": m.versao},
        "blocos": [{
            "id": b.id, "tipo": b.tipo, "numero": b.numero, "numero_modelo": b.numero_modelo,
            "texto": b.texto, "texto_modelo": b.texto_modelo, "situacao": b.situacao, "motivo": b.motivo,
            "origem": b.origem, "alterou_texto_fixo": b.alterou_texto_fixo, "referencias": b.referencias,
            "notas": notas.get(b.id, []), "campos": campos.get(b.id, []),
            "clausula_opcional": next((x.clausula_vermelha for x in m.blocos if x.id == b.id), False),
        } for b in mi.blocos],
        "removidos": [asdict(r) for r in mi.removidos],
        "pendencias": [asdict(p) for p in mi.pendencias],
        "resumo": {
            "blocos": len(mi.blocos),
            "iguais": sum(b.situacao == "igual" for b in mi.blocos),
            "alterados": sum(b.situacao == "alterado" for b in mi.blocos),
            "referencias": sum(b.situacao == "referencia" for b in mi.blocos),
            "removidos": len(mi.removidos),
            "pendencias": sum(p.tipo != "opcional" for p in mi.pendencias),
            "opcionais": sum(p.tipo == "opcional" for p in mi.pendencias),   # cláusulas opcionais da AGU a confirmar
            "texto_fixo_alterado": sum(b.alterou_texto_fixo for b in mi.blocos),
        },
        "html_sei": html_sei(mi),
    }


@router.post("/montar")
async def montar_minuta(pedido: PedidoMontagem):
    m = _modelo(pedido.modelo_id)
    return _serializar(m, montar(m, _decisoes(m, pedido)))


@router.get("/modelos/{modelo_id}/estrutura")
async def estrutura(modelo_id: str):
    """Blocos do modelo com numeração, campos, temas e notas (para conferência)."""
    m = _modelo(modelo_id)
    num = numerar(m.blocos)
    return {"versao": m.versao, "orientacoes": m.orientacoes, "blocos": [{
        "id": b.id, "tipo": b.tipo, "numero": num.get(b.id, ""), "texto": b.texto, "temas": sorted(b.temas),
        "notas": b.notas, "campos": [asdict(c) for c in b.campos], "clausula_opcional": b.clausula_vermelha,
    } for b in m.blocos if b.tipo != "sumario"]}


# ---------------------------------------------------------------------------
# IA (Gemini pelo navegador — padrão de relé)
# ---------------------------------------------------------------------------

@router.post("/texto")
async def texto_pdf(arquivos: list[UploadFile] = File(...)):
    """Texto dos PDFs do processo (TR, ETP, contrato) para mandar à IA."""
    import fitz
    saida = []
    for arquivo in arquivos:
        conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
        if len(conteudo) > TAMANHO_MAXIMO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{arquivo.filename}' passa de 20 MB.")
        try:
            with fitz.open(stream=conteudo, filetype="pdf") as doc:
                paginas = [p.get_text() for p in doc]
        except Exception:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{arquivo.filename}' não é um PDF legível.")
        texto = "\n".join(paginas)
        saida.append({"arquivo": arquivo.filename, "paginas": len(paginas), "caracteres": len(texto.strip()),
                      "sem_texto": len(texto.strip()) < 200, "texto": texto})
    return {"arquivos": saida}


class PedidoIA(PedidoMontagem):
    texto_tr: str = ""
    resposta: str = ""


def _contexto_ia(pedido: PedidoIA):
    if len(pedido.texto_tr.strip()) < 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Anexe o Termo de Referência (PDF com texto) para usar a IA.")
    m = _modelo(pedido.modelo_id)
    minuta = montar(m, _decisoes(m, pedido))
    decididos = {k.split(".")[0] for k in (*pedido.decisoes.remover, *pedido.decisoes.textos,
                                           *pedido.decisoes.campos, *pedido.decisoes.manter)}
    return m, minuta, pendencias_para_ia(m, minuta, decididos)


@router.post("/ia/prompt")
async def prompt_ia(pedido: PedidoIA):
    m, _, itens = _contexto_ia(pedido)
    if not itens:
        return {"aplicavel": False, "pendencias": 0}
    return {"aplicavel": True, "pendencias": len(itens),
            "prompt": montar_prompt(m, itens, pedido.texto_tr, pedido.dados, TIPOS[m.tipo])}


@router.post("/ia/validar")
async def validar_ia(pedido: PedidoIA):
    _, _, itens = _contexto_ia(pedido)
    r = validar(itens, pedido.resposta, pedido.texto_tr)
    d = r.decisoes
    return {
        "decisoes": {"remover": d.remover, "textos": d.textos, "campos": d.campos, "manter": sorted(d.manter),
                     "motivos": d.motivos, "origem": d.origem},
        "aplicadas": r.aplicadas, "descartes": r.descartes, "sem_informacao": r.sem_informacao,
        "pendencias_enviadas": len(itens),
    }
