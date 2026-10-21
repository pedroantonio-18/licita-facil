"""
Extrator de campos de documentos jurídicos brasileiros.

Arquitetura híbrida:
- Regex + validação matemática → CNPJ, CPF, CEP, telefone (instantâneo, auditável)
- Qwen2.5-1.5B (agentes especializados) → pessoas, empresas, vínculos, endereços

O texto é fatiado em parágrafos e cada parágrafo é classificado por gatilhos
antes de ser enviado ao agente correto. Isso mantém os prompts pequenos e
garante respostas rápidas mesmo em CPU sem GPU.
"""

import re
import os
import json
import logging
import importlib.util
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz

from app.extraction.patterns import (
    CNPJ_PATTERN, CPF_PATTERN, CEP_PATTERN, TELEFONE_PATTERN,
    SICAF_CONSULTANTE_PATTERN,
    normalize_cnpj, normalize_cpf, normalize_cep, normalize_telefone,
    cpf_valido, cnpj_valido,
    format_cpf, format_cnpj, format_cep,
)

logger = logging.getLogger("data_crossing.extraction.extractor")

# ---------------------------------------------------------------------------
# Modelo LLM — singleton carregado uma única vez
# ---------------------------------------------------------------------------

_LLM = None
_LLM_DISPONIVEL: Optional[bool] = None

# Caminho do modelo e threads são configuráveis: o servidor de produção tem 4 CPUs.
_LLM_MODEL_PATH = os.path.expanduser(
    os.environ.get("LLM_MODEL_PATH", "~/.models/qwen2.5-1.5b.gguf")
)
_LLM_THREADS = int(os.environ.get("LLM_THREADS", os.cpu_count() or 4))

AVISO_LLM_INDISPONIVEL = (
    "Extração de pessoas físicas não executada: o modelo local (llama_cpp + Qwen2.5) "
    "não está disponível neste servidor. Foram extraídos apenas CNPJ, CPF, CEP e "
    "telefone por expressões regulares; as regras R05 a R08 não terão dados de pessoas nem de endereços."
)


def _llm_disponivel() -> bool:
    """
    Verifica uma única vez se o llama_cpp está instalado e o modelo existe em disco.

    Sem esta checagem, _chamar_llm() falharia em silêncio e a extração
    devolveria zero pessoas sem nenhum aviso ao servidor.
    """
    global _LLM_DISPONIVEL
    if _LLM_DISPONIVEL is None:
        if importlib.util.find_spec("llama_cpp") is None:
            logger.warning("llama_cpp não instalado — extração de pessoas desativada.")
            _LLM_DISPONIVEL = False
        elif not os.path.isfile(_LLM_MODEL_PATH):
            logger.warning(f"Modelo não encontrado em {_LLM_MODEL_PATH} — extração de pessoas desativada.")
            _LLM_DISPONIVEL = False
        else:
            _LLM_DISPONIVEL = True
    return _LLM_DISPONIVEL


def _get_llm():
    global _LLM
    if _LLM is None:
        from llama_cpp import Llama
        logger.info("Carregando Qwen2.5-1.5B...")
        _LLM = Llama(
            model_path=_LLM_MODEL_PATH,
            n_ctx=3500,
            n_threads=_LLM_THREADS,
            n_gpu_layers=0,
            verbose=False,
        )
        logger.info("Modelo carregado.")
    return _LLM


def _chamar_llm(prompt: str, max_tokens: int = 512) -> dict:
    """
    Chama o Qwen com um prompt e retorna o JSON parseado.
    Retorna {} em caso de falha — nunca levanta exceção para o caller.
    """
    try:
        llm = _get_llm()
        response = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tokens,
        )
        raw = response["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Erro LLM: {e}")
        return {}


# ---------------------------------------------------------------------------
# Gatilhos para classificação de parágrafos
# ---------------------------------------------------------------------------

_GATILHOS_QUALIFICACAO = re.compile(
    r'\b(residente|domiciliado|domiciliada|nascido|nascida|natural de|'
    r'portador|portadora|filho de|filha de|filia[çc][aã]o|'
    r'sede|inscrita|inscrito|empresário|empresária|solteiro|solteira|'
    r'casado|casada|administrador|administradora|procurador|procuradora|'
    r'representante|titular|sócio|sócia|executor)\b',
    re.IGNORECASE,
)

_GATILHOS_RELACIONAMENTO = re.compile(
    r'\b(casado|casada|c[oô]njuge|uni[aã]o|comunh[aã]o|separa[çc][aã]o de bens|'
    r'regime de bens|certid[aã]o de casamento|matrimônio|esposa|marido)\b',
    re.IGNORECASE,
)

_GATILHOS_SOCIETARIO = re.compile(
    r'\b(quotas?|capital social|outorgante|outorgado|procura[çc][aã]o|'
    r'sócio|sócia|participação|percentual|integralizado|administra[çc][aã]o|'
    r'poderes|substabelecer|licitações?|concorrências?)\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class Campo:
    """Campo estruturado extraído por regex com rastreabilidade completa."""
    tipo: str
    valor: str
    valor_formatado: str
    pagina: int
    trecho: str
    metodo: str
    confianca: float = 1.0


@dataclass
class Pessoa:
    """Pessoa física com todos os vínculos relacionais identificados."""
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
    funcao: str = "não identificada"
    metodo: str = "qwen2.5"


@dataclass
class EmpresaExtraida:
    """Empresa identificada nos documentos com seus dados."""
    nome: str
    cnpj: Optional[str] = None
    nire: Optional[str] = None
    endereco: Optional[str] = None
    funcao_contrato: Optional[str] = None  # ex: concessionário, concedente, sócia
    metodo: str = "qwen2.5"


@dataclass
class ResultadoExtracao:
    """Resultado completo da extração de um documento."""
    cnpjs: list[Campo] = field(default_factory=list)
    cpfs: list[Campo] = field(default_factory=list)
    ceps: list[Campo] = field(default_factory=list)
    telefones: list[Campo] = field(default_factory=list)
    pessoas: list[Pessoa] = field(default_factory=list)
    empresas: list[EmpresaExtraida] = field(default_factory=list)
    paginas_processadas: int = 0
    metodo_principal: str = "regex+qwen2.5"
    avisos: list[str] = field(default_factory=list)
    # Dados encontrados mas excluídos do cruzamento, com o motivo (ex.: consultante SICAF)
    desconsiderados: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extrator principal
# ---------------------------------------------------------------------------

def extrair(
    texto_por_pagina: list[tuple[int, str]],
    metodo: str = "regex",
    usar_llm: bool = True,
) -> ResultadoExtracao:
    """
    Extrai todos os campos de uma lista de (num_pagina, texto).

    Fluxo:
    1. Regex varre cada página → CNPJ, CPF, CEP, telefone
    2. Parágrafos são classificados por gatilhos
    3. Agentes especializados do Qwen processam cada categoria
    4. Merge por CPF/CNPJ monta o resultado final
    """
    resultado = ResultadoExtracao(metodo_principal=metodo)
    resultado.paginas_processadas = len(texto_por_pagina)

    if usar_llm and not _llm_disponivel():
        usar_llm = False
        resultado.avisos.append(AVISO_LLM_INDISPONIVEL)

    cnpjs_vistos: set[str] = set()
    cpfs_vistos: set[str] = set()
    ceps_vistos: set[str] = set()
    telefones_vistos: set[str] = set()

    blocos_qualificacao: list[str] = []
    blocos_relacionamento: list[str] = []
    blocos_societario: list[str] = []

    # Passo 1: regex + classificação de parágrafos
    for num_pagina, texto in texto_por_pagina:
        if not texto or not texto.strip():
            continue

        _extrair_cnpjs(texto, num_pagina, metodo, resultado, cnpjs_vistos)
        _extrair_cpfs(texto, num_pagina, metodo, resultado, cpfs_vistos)
        _extrair_ceps(texto, num_pagina, metodo, resultado, ceps_vistos)
        _extrair_telefones(texto, num_pagina, metodo, resultado, telefones_vistos)

        if usar_llm:
            paragrafos = re.split(r'\n{2,}|(?<=[a-záàâãéêíóôõúç])\.\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ])', texto)
            for p in paragrafos:
                p = p.replace('\n', ' ').strip()
                if len(p) < 40:
                    continue
                if _GATILHOS_QUALIFICACAO.search(p):
                    blocos_qualificacao.append(p)
                if _GATILHOS_RELACIONAMENTO.search(p):
                    blocos_relacionamento.append(p)
                if _GATILHOS_SOCIETARIO.search(p):
                    blocos_societario.append(p)

    if not usar_llm:
        return resultado

    # Passo 2: agentes especializados
    nomes_vistos: set[str] = set()

    if blocos_qualificacao:
        texto_agente = " ".join(blocos_qualificacao)[:3000]
        _agente_qualificacao(texto_agente, resultado, nomes_vistos)

    if blocos_relacionamento:
        texto_agente = " ".join(blocos_relacionamento)[:2000]
        _agente_relacionamento(texto_agente, resultado, nomes_vistos)

    if blocos_societario:
        texto_agente = " ".join(blocos_societario)[:2000]
        _agente_societario(texto_agente, resultado, nomes_vistos)

    return resultado


# ---------------------------------------------------------------------------
# Extração por regex
# ---------------------------------------------------------------------------

def _trecho(texto: str, start: int, end: int, janela: int = 80) -> str:
    i = max(0, start - janela)
    f = min(len(texto), end + janela)
    return ("..." if i > 0 else "") + texto[i:f].replace('\n', ' ').strip() + "..."


def _extrair_cnpjs(texto, pagina, metodo, resultado, vistos):
    for m in CNPJ_PATTERN.finditer(texto):
        n = normalize_cnpj(m.group(1))
        if n in vistos or not cnpj_valido(n):
            continue
        vistos.add(n)
        resultado.cnpjs.append(Campo("cnpj", n, format_cnpj(n), pagina, _trecho(texto, m.start(), m.end()), metodo))


def _extrair_cpfs(texto, pagina, metodo, resultado, vistos):
    # CPF do usuário consultante no cabeçalho do SICAF não pertence à empresa
    for m in SICAF_CONSULTANTE_PATTERN.finditer(texto):
        n = normalize_cpf(m.group(1))
        if n in vistos or not cpf_valido(n):
            continue
        vistos.add(n)
        resultado.desconsiderados.append({
            "tipo": "cpf",
            "valor": n,
            "valor_formatado": format_cpf(n),
            "motivo": "CPF do usuário consultante no cabeçalho da consulta SICAF",
            "pagina": pagina,
            "trecho": _trecho(texto, m.start(), m.end()),
        })

    for m in CPF_PATTERN.finditer(texto):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        n = normalize_cpf(raw)
        if n in vistos or not cpf_valido(n):
            continue
        vistos.add(n)
        resultado.cpfs.append(Campo("cpf", n, format_cpf(n), pagina, _trecho(texto, m.start(), m.end()), metodo))


def _extrair_ceps(texto, pagina, metodo, resultado, vistos):
    for m in CEP_PATTERN.finditer(texto):
        n = normalize_cep(m.group(1))
        if len(n) != 8 or n in vistos:
            continue
        vistos.add(n)
        resultado.ceps.append(Campo("cep", n, format_cep(n), pagina, _trecho(texto, m.start(), m.end()), metodo))


def _extrair_telefones(texto, pagina, metodo, resultado, vistos):
    for m in TELEFONE_PATTERN.finditer(texto):
        ddd, p1, p2 = m.group(1), m.group(2), m.group(3)
        n = f"{ddd}{p1}{p2}"
        if n in vistos:
            continue
        vistos.add(n)
        resultado.telefones.append(Campo("telefone", n, normalize_telefone(ddd, p1, p2), pagina, _trecho(texto, m.start(), m.end()), metodo))


# ---------------------------------------------------------------------------
# Agentes especializados
# ---------------------------------------------------------------------------

def _merge_pessoa(resultado: ResultadoExtracao, dados: dict, nomes_vistos: set) -> None:
    """Insere ou mescla uma pessoa no resultado usando CPF ou nome como chave."""
    nome = (dados.get("nome") or "").strip()
    nome = " ".join(nome.split())
    if not nome or len(nome.split()) < 2:
        return

    cpf = dados.get("cpf") or None

    # Tenta encontrar pessoa já existente
    for p in resultado.pessoas:
        if cpf and p.cpf == cpf:
            # Merge por CPF — atualiza campos vazios
            if not p.filiacao_pai and dados.get("filiacao_pai"):
                p.filiacao_pai = dados["filiacao_pai"]
            if not p.filiacao_mae and dados.get("filiacao_mae"):
                p.filiacao_mae = dados["filiacao_mae"]
            if not p.conjuge and dados.get("conjuge"):
                p.conjuge = dados["conjuge"]
            if not p.endereco and dados.get("endereco"):
                p.endereco = dados["endereco"]
            if not p.nascimento and dados.get("nascimento"):
                p.nascimento = dados["nascimento"]
            if not p.funcao or p.funcao == "não identificada":
                p.funcao = dados.get("funcao") or p.funcao
            return

        chave = nome.upper().replace(" ", "")
        if fuzz.token_sort_ratio(chave, p.nome.upper().replace(" ", "")) >= 90:
            # Merge por nome similar
            if not p.conjuge and dados.get("conjuge"):
                p.conjuge = dados["conjuge"]
            if not p.endereco and dados.get("endereco"):
                p.endereco = dados["endereco"]
            return

    # Nova pessoa
    chave = nome.upper().replace(" ", "")
    if chave in nomes_vistos:
        return
    nomes_vistos.add(chave)

    resultado.pessoas.append(Pessoa(
        nome=nome,
        cpf=cpf,
        nascimento=dados.get("nascimento"),
        naturalidade=dados.get("naturalidade"),
        estado_civil=dados.get("estado_civil"),
        profissao=dados.get("profissao"),
        endereco=dados.get("endereco"),
        filiacao_pai=dados.get("filiacao_pai"),
        filiacao_mae=dados.get("filiacao_mae"),
        conjuge=dados.get("conjuge"),
        regime_bens=dados.get("regime_bens"),
        funcao=dados.get("funcao") or "não identificada",
    ))


def _agente_qualificacao(texto: str, resultado: ResultadoExtracao, nomes_vistos: set) -> None:
    """
    Agente 1: extrai pessoas físicas com qualificação completa.
    Foco: nome, CPF, nascimento, naturalidade, filiação, endereço, função.
    """
    prompt = f"""Você é um extrator de dados jurídicos brasileiros.
Extraia TODAS as pessoas físicas qualificadas no texto abaixo.
Retorne APENAS JSON válido, sem texto adicional:
{{"pessoas": [{{
  "nome": "nome completo",
  "cpf": "xxx.xxx.xxx-xx ou null",
  "nascimento": "dd/mm/aaaa ou null",
  "naturalidade": "cidade-UF ou null",
  "estado_civil": "casado/solteiro/etc ou null",
  "profissao": "profissão ou null",
  "endereco": "endereço completo ou null",
  "filiacao_pai": "nome do pai ou null",
  "filiacao_mae": "nome da mãe ou null",
  "funcao": "função no documento ou null"
}}]}}

TEXTO:
{texto}"""

    data = _chamar_llm(prompt, max_tokens=800)
    for p in data.get("pessoas", []):
        _merge_pessoa(resultado, p, nomes_vistos)


def _agente_relacionamento(texto: str, resultado: ResultadoExtracao, nomes_vistos: set) -> None:
    """
    Agente 2: extrai vínculos matrimoniais entre pessoas.
    Foco: quem é casado com quem e regime de bens.
    """
    prompt = f"""Extraia relações matrimoniais do texto jurídico abaixo.
Retorne APENAS JSON válido:
{{"casamentos": [{{
  "conjuge_1": "nome completo",
  "conjuge_2": "nome completo",
  "regime_bens": "comunhão parcial/separação absoluta/etc ou null"
}}]}}

TEXTO:
{texto}"""

    data = _chamar_llm(prompt, max_tokens=300)
    for c in data.get("casamentos", []):
        c1 = (c.get("conjuge_1") or "").strip()
        c2 = (c.get("conjuge_2") or "").strip()
        regime = c.get("regime_bens")

        if c1 and len(c1.split()) >= 2:
            _merge_pessoa(resultado, {"nome": c1, "conjuge": c2, "regime_bens": regime}, nomes_vistos)
        if c2 and len(c2.split()) >= 2:
            _merge_pessoa(resultado, {"nome": c2, "conjuge": c1, "regime_bens": regime}, nomes_vistos)


def _agente_societario(texto: str, resultado: ResultadoExtracao, nomes_vistos: set) -> None:
    """
    Agente 3: extrai estrutura societária e procuradores.
    Foco: sócios, participação, administradores, procuradores e poderes.
    """
    prompt = f"""Extraia a estrutura societária e procuradores do texto jurídico abaixo.
Retorne APENAS JSON válido:
{{"socios": [{{
  "nome": "nome ou razão social",
  "cpf_cnpj": "CPF ou CNPJ ou null",
  "participacao": "percentual ou null",
  "funcao": "sócio/administrador/procurador/etc"
}}],
"procuradores": [{{
  "nome": "nome completo",
  "cpf": "CPF ou null",
  "poderes": "resumo dos poderes ou null"
}}]}}

TEXTO:
{texto}"""

    data = _chamar_llm(prompt, max_tokens=500)

    for s in data.get("socios", []):
        nome = (s.get("nome") or "").strip()
        if not nome or len(nome.split()) < 2:
            continue
        _merge_pessoa(resultado, {
            "nome": nome,
            "cpf": s.get("cpf_cnpj"),
            "funcao": s.get("funcao") or "sócio",
        }, nomes_vistos)

    for p in data.get("procuradores", []):
        nome = (p.get("nome") or "").strip()
        if not nome or len(nome.split()) < 2:
            continue
        _merge_pessoa(resultado, {
            "nome": nome,
            "cpf": p.get("cpf"),
            "funcao": "procurador",
        }, nomes_vistos)