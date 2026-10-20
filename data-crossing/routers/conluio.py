"""
Router de análise de conluio em processos licitatórios.

Endpoints:
  POST   /conluio/identificar            → sugere razão social e CNPJ a partir dos PDFs (local, instantâneo)
  POST   /conluio/processar              → recebe PDFs de uma empresa, extrai localmente e salva
  POST   /conluio/importar               → recebe JSON do Gemini via frontend
  POST   /conluio/cruzar/{id}            → executa cruzamento entre empresas do processo
  GET    /conluio/parecer/{id}/prompt    → devolve o prompt do parecer para o navegador enviar ao Gemini
  POST   /conluio/parecer/{id}           → recebe a resposta do Gemini, valida e anexa à sessão
  GET    /conluio/relatorio/{id}         → devolve o relatório em PDF
  GET    /conluio/relatorios/{id}        → histórico de relatórios emitidos (hash SHA-256)
  GET    /conluio/sessao/{id}            → consulta dados extraídos para conferência
  DELETE /conluio/sessao/{id}            → remove a sessão

O backend não tem internet. Toda chamada ao Gemini é feita pelo navegador,
que repassa o resultado para cá (padrão de relé).
"""

import hashlib
import logging
import os
import re
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, status
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from app.crossing.parecer import montar_catalogo, montar_prompt, validar_parecer
from app.crossing.rules import cruzar_empresas, filtrar_ignorados, Empresa
from app.database import store
from app.extraction.extractor import extrair
from app.extraction.identificacao import identificar_empresa
from app.extraction.patterns import cnpj_valido, cpf_valido, format_cep, format_cnpj, format_cpf
from app.ingestion.detector import ingerir_pdf

logger = logging.getLogger("data_crossing.routers.conluio")

router = APIRouter(
    prefix="/conluio",
    tags=["Análise de Conluio"],
)

# OCR (docTR) das páginas digitalizadas na extração local. Desligado por padrão:
# em CPU, sem GPU, leva minutos por documento. Ative com OCR_ATIVO=1.
_OCR_ATIVO = os.environ.get("OCR_ATIVO", "0") == "1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serializar_pessoa(p, arquivo: str) -> dict:
    """Converte um objeto Pessoa para dict serializável."""
    return {
        "nome":         p.nome,
        "cpf":          p.cpf,
        "rg":           p.rg,
        "nascimento":   p.nascimento,
        "naturalidade": p.naturalidade,
        "estado_civil": p.estado_civil,
        "profissao":    p.profissao,
        "endereco":     p.endereco,
        "filiacao_pai": p.filiacao_pai,
        "filiacao_mae": p.filiacao_mae,
        "conjuge":      p.conjuge,
        "regime_bens":  p.regime_bens,
        "funcao":       p.funcao,
        "metodo":       p.metodo,
        "pagina":       0,
        "trecho":       f"Extraído pelo modelo local — {arquivo}",
        "arquivo":      arquivo,
    }


def _campo_dict(c, nome_empresa: str) -> dict:
    """Converte um CampoImport para o formato interno da sessão."""
    return {
        "valor":           re.sub(r'\D', '', c.valor),
        "valor_formatado": c.valor_formatado,
        "pagina":          0,
        "trecho":          c.trecho or f"Extraído pelo Gemini — {nome_empresa}",
        "arquivo":         "gemini",
    }


def _validar_campos(campos: list[dict], validador, formatador, tipo: str, empresa: str) -> tuple[list[dict], list[dict]]:
    """
    Separa os valores válidos dos inválidos.

    O Gemini devolve cada número duas vezes ("valor" só com dígitos e
    "valor_formatado") e às vezes erra um deles. Vale o primeiro que passar
    na validação; o valor guardado e o exibido passam a ser o mesmo número.
    Um número inválido nas duas formas não é cruzado, mas fica registrado
    no relatório para conferência.
    """
    validos, invalidos = [], []
    for c in campos:
        digitos_formatado = re.sub(r'\D', '', c["valor_formatado"] or "")
        valido = next((v for v in (c["valor"], digitos_formatado) if v and validador(v)), None)
        if valido:
            validos.append({**c, "valor": valido, "valor_formatado": formatador(valido)})
            continue
        lido = c["valor_formatado"] or c["valor"]
        if digitos_formatado and c["valor"] and digitos_formatado != c["valor"]:
            lido = f"{c['valor_formatado']} (dígitos lidos: {c['valor']})"
        invalidos.append({
            "empresa": empresa,
            "tipo": tipo,
            "valor": lido,
            "motivo": (
                "Dígito verificador inválido — provável erro de leitura do documento"
                if tipo in ("cnpj", "cpf") else "Formato inválido — provável erro de leitura do documento"
            ),
        })
    return validos, invalidos


def _obter_sessao(processo_id: str) -> dict:
    sessao = store.obter_sessao(processo_id)
    if sessao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Processo '{processo_id}' não encontrado.",
        )
    return sessao


def _gravar_empresa(processo_id: str, empresa: dict) -> None:
    """
    Insere a empresa na sessão. Reenviar a mesma empresa (mesmo CNPJ)
    substitui os dados anteriores em vez de duplicá-la.

    Como os dados mudaram, achados e parecer anteriores são descartados.
    """
    sessao = store.obter_sessao(processo_id) or {"empresas": []}
    sessao["empresas"] = [e for e in sessao["empresas"] if e["id"] != empresa["id"]]
    sessao["empresas"].append(empresa)
    sessao.pop("achados", None)
    sessao.pop("desconsiderados", None)
    sessao.pop("parecer", None)
    store.salvar_sessao(processo_id, sessao)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CampoImport(BaseModel):
    valor: str
    valor_formatado: str
    trecho: Optional[str] = None


class PessoaImport(BaseModel):
    nome: str
    cpf: Optional[str] = None
    rg: Optional[str] = None
    nascimento: Optional[str] = None
    naturalidade: Optional[str] = None
    estado_civil: Optional[str] = None
    profissao: Optional[str] = None
    endereco: Optional[str] = None
    filiacao_pai: Optional[str] = None
    filiacao_mae: Optional[str] = None
    conjuge: Optional[str] = None
    regime_bens: Optional[str] = None
    funcao: Optional[str] = None


class EnderecoImport(BaseModel):
    valor: str                       # endereço completo
    trecho: Optional[str] = None     # de quem é / contexto (ex.: "sede", "filial Jataí")


class EmpresaImport(BaseModel):
    processo_id: str
    empresa_nome: str
    empresa_cnpj: str
    cnpjs:     list[CampoImport] = []
    cpfs:      list[CampoImport] = []
    ceps:      list[CampoImport] = []
    telefones: list[CampoImport] = []
    pessoas:   list[PessoaImport] = []
    enderecos: list[EnderecoImport] = []
    # Modelo do Gemini que de fato respondeu (o navegador alterna entre modelos)
    modelo:    Optional[str] = None


class ParecerImport(BaseModel):
    modelo: str = ""
    # Texto bruto devolvido pelo Gemini ou o JSON já parseado pelo navegador
    resposta: Any


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/identificar")
async def identificar(arquivos: list[UploadFile] = File(..., description="PDFs da empresa")):
    """
    Sugere razão social e CNPJ da empresa a partir do texto dos PDFs.

    Roda localmente (sem Gemini e sem LLM), para preencher a tela assim que
    os arquivos são anexados. O servidor confere e pode editar os campos.
    """
    textos: list[str] = []
    for arquivo in arquivos:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await arquivo.read())
            tmp_path = tmp.name
        try:
            documento = ingerir_pdf(tmp_path, usar_ocr=False)
            textos.extend(texto for _, texto in documento.texto_por_pagina())
        except Exception as e:
            logger.warning(f"Não foi possível ler '{arquivo.filename}': {e}")
        finally:
            os.unlink(tmp_path)
    return identificar_empresa(textos)


@router.post("/processar")
async def processar_documentos(
    processo_id: str = Form(..., description="Identificador do processo licitatório"),
    empresa_nome: str = Form(..., description="Razão social da empresa"),
    empresa_cnpj: str = Form(..., description="CNPJ principal da empresa (apenas dígitos)"),
    arquivos: list[UploadFile] = File(..., description="PDFs da empresa"),
):
    """
    Recebe os PDFs de uma empresa, extrai os dados localmente e armazena na sessão.
    Usado quando não há chave do Gemini. Chame uma vez por empresa; depois, /cruzar.
    """
    empresa_id = re.sub(r'\D', '', empresa_cnpj)

    cnpjs_acumulados     = []
    cpfs_acumulados      = []
    ceps_acumulados      = []
    telefones_acumulados = []
    pessoas_acumuladas   = []
    documentos_processados = []
    avisos: list[str] = []
    desconsiderados: list[dict] = []

    for arquivo in arquivos:
        if arquivo.content_type != "application/pdf":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"O arquivo '{arquivo.filename}' não é um PDF válido.",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            conteudo = await arquivo.read()
            tmp.write(conteudo)
            tmp_path = tmp.name

        try:
            documento = ingerir_pdf(tmp_path, usar_ocr=_OCR_ATIVO)
            resultado = extrair(documento.texto_por_pagina())

            for destino, campos in (
                (cnpjs_acumulados, resultado.cnpjs),
                (cpfs_acumulados, resultado.cpfs),
                (ceps_acumulados, resultado.ceps),
                (telefones_acumulados, resultado.telefones),
            ):
                destino.extend(
                    {"valor": c.valor, "valor_formatado": c.valor_formatado,
                     "pagina": c.pagina, "trecho": c.trecho, "arquivo": arquivo.filename}
                    for c in campos
                )
            pessoas_acumuladas.extend(
                _serializar_pessoa(p, arquivo.filename) for p in resultado.pessoas
            )
            desconsiderados.extend(
                {**d, "empresa": empresa_nome, "arquivo": arquivo.filename}
                for d in resultado.desconsiderados
            )
            for aviso in resultado.avisos:
                if aviso not in avisos:
                    avisos.append(aviso)
            if documento.paginas_digitalizadas and not _OCR_ATIVO:
                avisos.append(
                    f"'{arquivo.filename}': {documento.paginas_digitalizadas} página(s) "
                    "digitalizada(s) sem OCR (OCR_ATIVO=0) — o conteúdo dessas páginas não foi analisado."
                )
            documentos_processados.append({
                "arquivo":       arquivo.filename,
                "hash":          documento.hash_sha256,
                "paginas":       documento.total_paginas,
                "pesquisaveis":  documento.paginas_pesquisaveis,
                "digitalizadas": documento.paginas_digitalizadas,
            })

        finally:
            os.unlink(tmp_path)

    _gravar_empresa(processo_id, {
        "id":               empresa_id,
        "nome":             empresa_nome,
        "cnpj_principal":   empresa_id,
        "origem":           "extração local",
        "cnpjs":            cnpjs_acumulados,
        "cpfs":             cpfs_acumulados,
        "ceps":             ceps_acumulados,
        "telefones":        telefones_acumulados,
        "pessoas":          pessoas_acumuladas,
        "documentos":       documentos_processados,
        "avisos":           avisos,
        "desconsiderados_extracao": desconsiderados,
    })

    return JSONResponse({
        "processo_id":           processo_id,
        "empresa":               empresa_nome,
        "cnpjs_encontrados":     len(cnpjs_acumulados),
        "cpfs_encontrados":      len(cpfs_acumulados),
        "ceps_encontrados":      len(ceps_acumulados),
        "telefones_encontrados": len(telefones_acumulados),
        "pessoas_encontradas":   len(pessoas_acumuladas),
        "documentos":            documentos_processados,
        "avisos":                avisos,
    })


@router.post("/importar")
async def importar_dados_gemini(dados: EmpresaImport):
    """
    Recebe dados já extraídos pelo Gemini via frontend JS.

    O frontend chama a API do Gemini diretamente do navegador (que tem internet),
    recebe o JSON estruturado e envia para cá. O data-crossing não processa PDF —
    apenas armazena e prepara para o cruzamento.
    """
    empresa_id  = re.sub(r'\D', '', dados.empresa_cnpj)
    processo_id = dados.processo_id

    cnpjs     = [_campo_dict(c, dados.empresa_nome) for c in dados.cnpjs]
    cpfs      = [_campo_dict(c, dados.empresa_nome) for c in dados.cpfs]
    ceps      = [_campo_dict(c, dados.empresa_nome) for c in dados.ceps]
    telefones = [_campo_dict(t, dados.empresa_nome) for t in dados.telefones]

    cnpjs, cnpjs_invalidos = _validar_campos(cnpjs, cnpj_valido, format_cnpj, "cnpj", dados.empresa_nome)
    cpfs, cpfs_invalidos = _validar_campos(cpfs, cpf_valido, format_cpf, "cpf", dados.empresa_nome)
    ceps, ceps_invalidos = _validar_campos(ceps, lambda v: len(v) == 8, format_cep, "cep", dados.empresa_nome)
    invalidos = cnpjs_invalidos + cpfs_invalidos + ceps_invalidos

    pessoas = []
    cpfs_presentes = {c["valor"] for c in cpfs}
    for p in dados.pessoas:
        pessoa = {
            **p.model_dump(),
            "funcao":  p.funcao or "não identificada",
            "pagina":  0,
            "trecho":  f"Extraído pelo Gemini — {dados.empresa_nome}",
            "arquivo": "gemini",
        }
        cpf = re.sub(r'\D', '', p.cpf or "")
        if cpf and not cpf_valido(cpf):
            invalidos.append({
                "empresa": dados.empresa_nome,
                "tipo": "cpf",
                "valor": f"{p.cpf} ({p.nome})",
                "motivo": "Dígito verificador inválido — provável erro de leitura do documento",
            })
            pessoa["cpf"] = None
        elif cpf and cpf not in cpfs_presentes:
            # CPF citado só na qualificação da pessoa também entra no cruzamento (R02)
            cpfs.append({
                "valor":           cpf,
                "valor_formatado": format_cpf(cpf),
                "pagina":          0,
                "trecho":          f"CPF na qualificação de {p.nome} — Gemini, {dados.empresa_nome}",
                "arquivo":         "gemini",
            })
            cpfs_presentes.add(cpf)
        pessoas.append(pessoa)

    _gravar_empresa(processo_id, {
        "id":             empresa_id,
        "nome":           dados.empresa_nome,
        "cnpj_principal": empresa_id,
        "origem":         f"Gemini {dados.modelo} (via navegador)" if dados.modelo else "Gemini (via navegador)",
        "cnpjs":          cnpjs,
        "cpfs":           cpfs,
        "ceps":           ceps,
        "telefones":      telefones,
        "pessoas":        pessoas,
        "enderecos": [
            {"valor": e.valor, "trecho": e.trecho or f"Endereço — {dados.empresa_nome}", "pagina": 0}
            for e in dados.enderecos if e.valor.strip()
        ],
        "documentos": [{
            "arquivo":       "gemini",
            "hash":          "gemini_extraction",
            "paginas":       0,
            "pesquisaveis":  0,
            "digitalizadas": 0,
        }],
        "avisos": [],
        "desconsiderados_extracao": invalidos,
    })

    return JSONResponse({
        "processo_id":          processo_id,
        "empresa":              dados.empresa_nome,
        "cnpjs_importados":     len(cnpjs),
        "cpfs_importados":      len(cpfs),
        "ceps_importados":      len(ceps),
        "telefones_importados": len(telefones),
        "pessoas_importadas":   len(pessoas),
        "invalidos_descartados": len(invalidos),
        "status":               "importado com sucesso",
    })


@router.post("/cruzar/{processo_id}")
async def cruzar(processo_id: str):
    """Executa cruzamento entre todas as empresas do processo."""
    sessao = _obter_sessao(processo_id)
    if len(sessao["empresas"]) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário processar pelo menos 2 empresas antes de cruzar.",
        )

    empresas: list[Empresa] = []
    desconsiderados: list[dict] = []
    for e in sessao["empresas"]:
        desconsiderados.extend(e.get("desconsiderados_extracao", []))
        filtrada, ignorados = filtrar_ignorados(Empresa(
            id=e["id"],
            nome=e["nome"],
            cnpj_principal=e["cnpj_principal"],
            cnpjs=e["cnpjs"],
            cpfs=e["cpfs"],
            ceps=e["ceps"],
            telefones=e["telefones"],
            pessoas=e["pessoas"],
            enderecos=e.get("enderecos", []),
        ))
        empresas.append(filtrada)
        desconsiderados.extend(ignorados)

    achados = cruzar_empresas(empresas)

    sessao["achados"] = [
        {
            "id":              a.id,
            "prioridade":      a.prioridade,
            "regra_codigo":    a.regra_codigo,
            "regra_descricao": a.regra_descricao,
            "empresa_a":       a.empresa_a_nome,
            "empresa_b":       a.empresa_b_nome,
            "campo":           a.campo,
            "valor":           a.valor,
            "similaridade":    a.similaridade,
            "evidencia_a":     a.evidencia_a,
            "evidencia_b":     a.evidencia_b,
            "nota":            a.nota,
        }
        for a in achados
    ]
    sessao["desconsiderados"] = desconsiderados
    # Os ids dos achados podem ter mudado: um parecer anterior não vale mais
    sessao.pop("parecer", None)
    store.salvar_sessao(processo_id, sessao)

    return JSONResponse({
        "processo_id":          processo_id,
        "empresas_analisadas":  len(empresas),
        "total_achados":        len(achados),
        "achados":              sessao["achados"],
        "desconsiderados":      desconsiderados,
        "avisos":               [a for e in sessao["empresas"] for a in e.get("avisos", [])],
    })


@router.get("/parecer/{processo_id}/prompt")
async def prompt_parecer(processo_id: str):
    """
    Devolve o prompt do parecer preliminar. O navegador o envia ao Gemini
    e devolve a resposta em POST /conluio/parecer/{id}.

    Vale também sem achados: a avaliação geral cita o catálogo de dados.
    """
    sessao = _obter_sessao(processo_id)
    if "achados" not in sessao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execute o cruzamento antes de solicitar o parecer.",
        )
    catalogo = montar_catalogo(sessao)
    return {
        "aplicavel": True,
        "prompt": montar_prompt(processo_id, sessao["achados"], catalogo),
        "ids": [a["id"] for a in sessao["achados"]] + list(catalogo),
    }


@router.post("/parecer/{processo_id}")
async def registrar_parecer(processo_id: str, dados: ParecerImport):
    """Valida a resposta do Gemini e anexa o parecer à sessão."""
    sessao = _obter_sessao(processo_id)
    if "achados" not in sessao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execute o cruzamento antes de registrar o parecer.",
        )

    achados = sessao["achados"]
    ids_validos = {a["id"] for a in achados} | set(montar_catalogo(sessao))
    ids_alta = {a["id"] for a in achados if a.get("prioridade") == "alta"}
    parecer = validar_parecer(dados.resposta, ids_validos, modelo=dados.modelo, ids_alta=ids_alta)
    sessao["parecer"] = parecer
    store.salvar_sessao(processo_id, sessao)
    return parecer


@router.get("/relatorio/{processo_id}")
async def gerar_relatorio(processo_id: str):
    """Gera e devolve o relatório em PDF; registra o hash SHA-256 emitido."""
    sessao = _obter_sessao(processo_id)
    if "achados" not in sessao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execute o cruzamento antes de gerar o relatório.",
        )

    from app.report.generator import gerar_pdf_relatorio
    pdf_bytes = gerar_pdf_relatorio(processo_id, sessao)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    store.registrar_relatorio(
        processo_id, sha256, len(sessao["achados"]), com_parecer="parecer" in sessao
    )

    nome = re.sub(r"[^\w.-]", "_", processo_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="relatorio_{nome}.pdf"',
            "X-Relatorio-SHA256": sha256,
        },
    )


@router.get("/relatorios/{processo_id}")
async def historico_relatorios(processo_id: str):
    """Lista os relatórios emitidos para o processo, com hash para conferência."""
    return {"processo_id": processo_id, "relatorios": store.listar_relatorios(processo_id)}


@router.get("/sessao/{processo_id}")
async def consultar_sessao(processo_id: str):
    """Retorna dados extraídos para conferência."""
    return JSONResponse(_obter_sessao(processo_id))


@router.delete("/sessao/{processo_id}")
async def limpar_sessao(processo_id: str):
    """Remove os dados de um processo."""
    store.remover_sessao(processo_id)
    return {"message": f"Sessão '{processo_id}' removida."}
