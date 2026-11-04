"""
Juntada de documentos de habilitação.

Endpoints:
  GET    /juntada/config                    → tipos de certidão, padrões e se a consulta ao TCU está ativa
  POST   /juntada/identificar               → sugere razão social e CNPJ a partir das certidões
  POST   /juntada/conferir                  → recebe as certidões de uma empresa e devolve o checklist
  POST   /juntada/{sessao}/tcu              → consulta consolidada do TCU automática (fase 2, se liberada)
  POST   /juntada/{sessao}/manual           → servidor marca um item como conferido, com justificativa
  DELETE /juntada/{sessao}/manual/{cnpj}/{tipo} → desfaz a conferência manual
  GET    /juntada/{sessao}/bloco/{cnpj}/{n} → PDF do bloco n da empresa para o SEI (1 jurídica, 2 regularidade,
                                             3 idoneidade, 4 econômico-financeira)
  GET    /juntada/{sessao}/relatorio        → relatório de conferência de todas as empresas
  DELETE /juntada/{sessao}                  → apaga a sessão

O serviço funciona offline. Receita, FGTS e Trabalhista têm CAPTCHA e são
emitidas pelo servidor nos sites; o sistema confere e organiza.
"""

import re
import unicodedata
from datetime import date, datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app import sessoes, tcu
from app.analise import analisar_empresa, arquivos_recebidos, parametros, serializar
from app.certidoes import BLOCOS, TIPOS, TIPOS_POR_ID
from app.conferencia import PADRAO_OBRIGATORIAS, POR_OBJETO, obrigatorias_padrao
from app.identificacao import identificar
from app.montagem import documentos_por_bloco, pdf_bloco, relatorio_conferencia
from app.texto import apenas_digitos, cnpj_valido

router = APIRouter(prefix="/juntada", tags=["Juntada de documentos"])

LIMITE_ARQUIVO = 50 * 1024 * 1024


def _sessao(sessao_id: str) -> dict:
    try:
        return sessoes.carregar(sessao_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sessão não encontrada ou expirada. Confira novamente.")


async def _ler_pdf(arquivo: UploadFile) -> bytes:
    conteudo = await arquivo.read()
    if len(conteudo) > LIMITE_ARQUIVO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{arquivo.filename}' passa de 50 MB.")
    if not conteudo.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{arquivo.filename}' não é um PDF.")
    return conteudo


def _empresa(meta: dict, empresa_cnpj: str) -> str:
    cnpj = apenas_digitos(empresa_cnpj)
    if cnpj not in meta["empresas"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Empresa não conferida nesta sessão.")
    return cnpj


def _analisar(sessao_id: str, meta: dict, cnpj: str):
    """Conferência da empresa com as decisões manuais do servidor já aplicadas."""
    return analisar_empresa(sessoes.pasta_arquivos(sessao_id, cnpj), cnpj, parametros(meta),
                            meta["empresas"][cnpj].get("manuais", {}))


def _resposta(sessao_id: str, meta: dict, cnpj: str) -> dict:
    nome = meta["empresas"][cnpj]["nome"]
    itens = _analisar(sessao_id, meta, cnpj)
    empresa = serializar(nome, cnpj, itens)
    empresa["arquivos"] = arquivos_recebidos(sessoes.pasta_arquivos(sessao_id, cnpj))
    empresa["blocos"] = [
        {"numero": n, "nome": BLOCOS[n], "documentos": len(docs)}
        for n, docs in sorted(documentos_por_bloco(itens).items())
    ]
    return {"sessao_id": sessao_id, "empresa": empresa}


def _nome_download(texto: str) -> str:
    """Nome de arquivo só com ASCII: acento no cabeçalho Content-Disposition quebra o download."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9.-]+", "_", ascii_).strip("_")[:80] or "documento"


@router.get("/config")
async def config():
    return {
        "tipos": [{"id": t.id, "nome": t.nome, "bloco": t.bloco}
                  for t in sorted(TIPOS, key=lambda t: (t.bloco, t.ordem)) if t.id != "sicaf"],
        "blocos": BLOCOS,
        "objetos": {"compras": "Compra de bens/materiais", "servicos": "Serviços", "ambos": "Bens e serviços"},
        "obrigatorias_por_objeto": {o: obrigatorias_padrao(o) for o in POR_OBJETO},
        "obrigatorias_padrao": PADRAO_OBRIGATORIAS,
        "dias_consultas_padrao": 30,
        "dias_falencia_padrao": 30,
        "consulta_tcu_ativa": tcu.ativa(),
    }


@router.post("/identificar")
async def identificar_empresa(arquivos: list[UploadFile] = File(...)):
    import fitz
    textos: list[str] = []
    for arquivo in arquivos:
        try:
            with fitz.open(stream=await _ler_pdf(arquivo), filetype="pdf") as doc:
                textos.extend(p.get_text() for p in doc)
        except HTTPException:
            continue
    return identificar(textos)


@router.post("/conferir")
async def conferir(
    processo_id: str = Form(...),
    data_referencia: date = Form(...),
    empresa_nome: str = Form(...),
    empresa_cnpj: str = Form(...),
    arquivos: list[UploadFile] = File(...),
    sessao_id: str | None = Form(None),
    obrigatorias: str | None = Form(None),
    objeto: str = Form("compras"),
    dias_consultas: int = Form(30),
    dias_falencia: int = Form(30),
):
    """
    Recebe todas as certidões de uma empresa (substitui envios anteriores
    dela) e devolve o checklist. Chame uma vez por empresa, com o mesmo
    sessao_id, e depois baixe os PDFs.
    """
    cnpj = apenas_digitos(empresa_cnpj)
    if not cnpj_valido(cnpj):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"CNPJ inválido: {empresa_cnpj}")

    sessoes.limpar_antigas()
    if sessao_id:
        meta = _sessao(sessao_id)
    else:
        sessao_id = sessoes.criar()
        meta = sessoes.carregar(sessao_id)

    meta.update({
        "processo_id": processo_id,
        "data_referencia": data_referencia.isoformat(),
        "objeto": objeto if objeto in POR_OBJETO else "compras",
        "obrigatorias": ([t for t in obrigatorias.split(",") if t] if obrigatorias is not None
                         else obrigatorias_padrao(objeto)),
        "dias_consultas": max(0, dias_consultas),
        "dias_falencia": max(0, dias_falencia),
    })

    pasta = sessoes.pasta_arquivos(sessao_id, cnpj)
    for antigo in pasta.glob("*.pdf"):
        antigo.unlink()
    existentes: set[str] = set()
    for arquivo in arquivos:
        conteudo = await _ler_pdf(arquivo)
        nome = sessoes.nome_seguro(arquivo.filename, existentes)
        existentes.add(nome)
        (pasta / nome).write_bytes(conteudo)

    # Arquivos novos: decisões manuais anteriores sobre esta empresa não valem mais
    meta["empresas"][cnpj] = {"nome": empresa_nome, "manuais": {}}
    sessoes.salvar(sessao_id, meta)
    return _resposta(sessao_id, meta, cnpj)


@router.post("/{sessao_id}/tcu")
async def consultar_tcu(sessao_id: str, empresa_cnpj: str = Form(...)):
    """Baixa a consulta consolidada do TCU e a acrescenta às certidões da empresa."""
    meta = _sessao(sessao_id)
    cnpj = _empresa(meta, empresa_cnpj)
    try:
        pdf = tcu.consultar(cnpj)
    except tcu.ConsultaIndisponivel as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    pasta = sessoes.pasta_arquivos(sessao_id, cnpj)
    nome = sessoes.nome_seguro(f"TCU_consulta_consolidada_{date.today():%Y%m%d}.pdf", {p.name for p in pasta.glob("*.pdf")})
    (pasta / nome).write_bytes(pdf)
    meta["empresas"][cnpj].get("manuais", {}).pop("tcu", None)   # nova consulta substitui a decisão manual
    sessoes.salvar(sessao_id, meta)
    return _resposta(sessao_id, meta, cnpj)


@router.post("/{sessao_id}/manual")
async def registrar_conferencia_manual(
    sessao_id: str,
    empresa_cnpj: str = Form(...),
    tipo: str = Form(...),
    justificativa: str = Form(...),
):
    """
    O servidor dá como conferido um item que o sistema não pôde marcar OK
    (ex.: CNJ indisponível e o CNIA foi consultado direto no site; certidão
    dispensada pelo edital). A justificativa é obrigatória e aparece na
    folha de rosto e no relatório, junto com a situação apontada pelo sistema.
    """
    meta = _sessao(sessao_id)
    cnpj = _empresa(meta, empresa_cnpj)
    if tipo not in TIPOS_POR_ID and tipo != "outro":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tipo de certidão desconhecido: {tipo}")
    justificativa = " ".join(justificativa.split())
    if len(justificativa) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Descreva a justificativa (mínimo de 10 caracteres).")
    meta["empresas"][cnpj].setdefault("manuais", {})[tipo] = {
        "justificativa": justificativa[:500],
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    }
    sessoes.salvar(sessao_id, meta)
    return _resposta(sessao_id, meta, cnpj)


@router.delete("/{sessao_id}/manual/{empresa_cnpj}/{tipo}")
async def desfazer_conferencia_manual(sessao_id: str, empresa_cnpj: str, tipo: str):
    meta = _sessao(sessao_id)
    cnpj = _empresa(meta, empresa_cnpj)
    meta["empresas"][cnpj].get("manuais", {}).pop(tipo, None)
    sessoes.salvar(sessao_id, meta)
    return _resposta(sessao_id, meta, cnpj)


@router.get("/{sessao_id}/bloco/{empresa_cnpj}/{numero}")
async def baixar_bloco(sessao_id: str, empresa_cnpj: str, numero: int):
    """PDF único de um bloco temático da empresa, para juntar no SEI."""
    meta = _sessao(sessao_id)
    cnpj = _empresa(meta, empresa_cnpj)
    if numero not in BLOCOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bloco inexistente.")
    documentos = documentos_por_bloco(_analisar(sessao_id, meta, cnpj)).get(numero)
    if not documentos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nenhum documento no bloco {numero} ({BLOCOS[numero]}).")
    pdf = pdf_bloco(documentos, sessoes.pasta_arquivos(sessao_id, cnpj))
    nome = _nome_download(meta["empresas"][cnpj]["nome"])
    arquivo = f"bloco{numero}_{_nome_download(BLOCOS[numero])}_{nome}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{arquivo}"'})


@router.get("/{sessao_id}/relatorio")
async def baixar_relatorio(sessao_id: str):
    meta = _sessao(sessao_id)
    p = parametros(meta)
    empresas = [
        (dados["nome"], cnpj, _analisar(sessao_id, meta, cnpj),
         arquivos_recebidos(sessoes.pasta_arquivos(sessao_id, cnpj)))
        for cnpj, dados in meta["empresas"].items()
    ]
    pdf = relatorio_conferencia(meta["processo_id"], p, empresas)
    arquivo = f"conferencia_certidoes_{_nome_download(meta['processo_id'])}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{arquivo}"'})


@router.delete("/{sessao_id}")
async def apagar(sessao_id: str):
    try:
        sessoes.remover(sessao_id)
    except KeyError:
        pass
    return {"message": "Sessão removida."}
