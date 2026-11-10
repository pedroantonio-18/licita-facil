"""
Endpoints do enquadramento de despesas (Informação de estimativa e enquadramento para o SEI).
Sem estado: a tela manda os dados e recebe o enquadramento calculado e o texto pronto.
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation

import json

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.extenso import formatar_reais, ler_reais
from app.informacao import METODOLOGIAS, NOMES_METODOLOGIAS, DadosInformacao, html_sei, montar
from app import pca
from app.regras import LIMITE_ME_EPP, NATUREZAS, Demanda, Item, enquadrar, limites

router = APIRouter(prefix="/enquadramento", tags=["Enquadramento"])


class ItemEntrada(BaseModel):
    descricao: str = ""
    valor: str
    divisivel: bool = False


class DemandaEntrada(BaseModel):
    descricao: str = ""
    origem: str = ""
    valor: str
    ja_contratada: bool = False
    propria: bool = False


class PedidoGerar(BaseModel):
    natureza: str
    exercicio: str
    itens: list[ItemEntrada]
    demandas: list[DemandaEntrada] = Field(default_factory=list)
    forcar_licitacao: bool = False
    grupo_unico: bool = False
    dados: dict = Field(default_factory=dict)


def _valor(texto: str, onde: str) -> Decimal:
    try:
        v = ler_reais(texto)
    except (InvalidOperation, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Valor inválido em {onde}: “{texto}”.")
    if v < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Valor negativo em {onde}.")
    return v


@router.get("/config")
async def config():
    return {"naturezas": NATUREZAS, "metodologias": NOMES_METODOLOGIAS,
            "limite_me_epp": formatar_reais(LIMITE_ME_EPP), "pca": pca.anos(), "pedido_ia_pca": pca.PEDIDO_IA,
            "limites": {ano: {**v, "I": formatar_reais(Decimal(v["I"])), "II": formatar_reais(Decimal(v["II"]))}
                        for ano, v in limites().items()}}


@router.post("/gerar")
async def gerar(pedido: PedidoGerar):
    itens = [Item(i.descricao.strip() or f"Item {n}", _valor(i.valor, f"item {n}"), i.divisivel)
             for n, i in enumerate(pedido.itens, 1) if str(i.valor).strip()]
    demandas = [Demanda(d.descricao.strip() or f"Demanda {n}", d.origem.strip(), _valor(d.valor, f"demanda {n}"),
                        d.ja_contratada, d.propria)
                for n, d in enumerate(pedido.demandas, 1) if str(d.valor).strip()]
    try:
        e = enquadrar(pedido.natureza, itens, demandas, pedido.exercicio.strip(), pedido.forcar_licitacao, pedido.grupo_unico)
    except ValueError as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    nomes = {f.name for f in fields(DadosInformacao)}
    dados = DadosInformacao(**{k: v for k, v in pedido.dados.items() if k in nomes})
    if dados.metodologia not in METODOLOGIAS:
        dados.metodologia = "media_saneada"
    ps = montar(dados, e, pedido.natureza, itens, demandas)
    pendencias = sum(p.texto.count("[informar") for p in ps)
    return {
        "enquadramento": {
            "modalidade": e.modalidade, "inciso": e.inciso, "limite": formatar_reais(e.limite), "decreto": e.decreto,
            "limite_confirmado": e.limite_confirmado, "exercicio": e.exercicio,
            "valor_estimado": formatar_reais(e.valor_estimado), "soma_exercicio": formatar_reais(e.soma_exercicio),
            "fracionamento_ok": e.fracionamento_ok, "me_epp": e.me_epp,
            "seguridade": formatar_reais(e.seguridade) if e.seguridade is not None else None,
        },
        "avisos": e.avisos,
        "pendencias": pendencias,
        "paragrafos": [{"tipo": p.tipo, "texto": p.texto, "linhas": p.linhas} for p in ps],
        "html_sei": html_sei(ps),
    }


# ---------------------------------------------------------------------------
# PCA (Plano de Contratações Anual) — fracionamento
# ---------------------------------------------------------------------------

TAMANHO_MAXIMO = 30 * 1024 * 1024


def _ano(ano: str) -> str:
    if not ano.isdigit() or len(ano) != 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Exercício inválido.")
    return ano


@router.post("/pca/{ano}")
async def enviar_pca(ano: str, arquivo: UploadFile = File(...)):
    """PDF do PCA publicado no portal da SJGO. Se a tabela estiver em imagem, nada é lido
    e a tela oferece a importação da lista (JSON) obtida com a IA do servidor."""
    _ano(ano)
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Arquivo passa de 30 MB.")
    try:
        demandas = pca.ler_pdf(conteudo)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não foi possível ler o arquivo como PDF.")
    if not demandas:
        return {"ano": ano, "demandas": 0, "em_imagem": True}
    pca.salvar(ano, demandas, f"PDF {arquivo.filename}")
    return {"ano": ano, "demandas": len(demandas), "em_imagem": False}


class ListaPCA(BaseModel):
    resposta: str


@router.post("/pca/{ano}/lista")
async def importar_lista_pca(ano: str, lista: ListaPCA):
    """Lista de demandas em JSON (ex.: transcrita pela IA do servidor de um PCA em imagem)."""
    _ano(ano)
    texto = lista.resposta.strip().replace("\u201c", '"').replace("\u201d", '"')
    inicio, fim = texto.find("{"), texto.rfind("}")
    inicio_lista = texto.find("[")
    try:
        if inicio != -1 and (inicio_lista == -1 or inicio < inicio_lista):
            dados = json.loads(texto[inicio:fim + 1])
        else:
            dados = json.loads(texto[inicio_lista:texto.rfind("]") + 1])
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não encontrei a lista (JSON) na resposta colada.")
    if isinstance(dados, dict) and dados.get("erro"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A IA informou: {dados['erro']}. Anexe o PDF do PCA e tente de novo.")
    demandas = pca.de_json(dados)
    if not demandas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A lista não tem demandas com descrição.")
    pca.salvar(ano, demandas, "lista colada pelo servidor")
    return {"ano": ano, "demandas": len(demandas)}


class BuscaPCA(BaseModel):
    objeto: str


@router.post("/pca/{ano}/buscar")
async def buscar_pca(ano: str, busca: BuscaPCA):
    demandas = pca.carregar(_ano(ano))
    if not demandas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"PCA de {ano} ainda não carregado.")
    return {"ano": ano, "total": len(demandas), "sugestoes": pca.buscar(demandas, busca.objeto)}
