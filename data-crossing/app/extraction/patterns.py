"""
Padrões de extração e validadores para documentos societários brasileiros.

Todos os padrões são compilados uma única vez no import para performance.
A validação de dígito verificador garante que apenas CPFs e CNPJs
matematicamente válidos sejam aceitos, eliminando falsos positivos.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Padrões compilados (O Trabalho Braçal)
# ---------------------------------------------------------------------------

# CNPJ: aceita com ou sem formatação
CNPJ_PATTERN = re.compile(
    r'\b(\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\s]?\d{4}[-\s]?\d{2})\b'
)

# CPF: aceita com ou sem formatação, e a variante C.P.F: usada em cartórios
CPF_PATTERN = re.compile(
    r'(?:C\.?P\.?F\.?[:\s]*)(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})'
    r'|'
    r'\b(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2})\b'
)

# CEP: aceita com ou sem hífen, com ou sem ponto
CEP_PATTERN = re.compile(
    r'CEP[:\s]*(\d{2}\.?\d{3}[-\s]?\d{3})'
)

# Telefone: exige DDD entre parênteses para evitar capturar números de registro
TELEFONE_PATTERN = re.compile(
    r'\((\d{2})\)\s?(\d{4,5})[-\s]?(\d{4})'
)

# Cabeçalho das consultas SICAF: "NOME DO SERVIDOR 000.000.000-00 - Governo (Uasg: 90022)".
# O CPF é do usuário consultante (servidor público), não da empresa licitante.
SICAF_CONSULTANTE_PATTERN = re.compile(
    r'(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\s*-\s*Governo\b',
    re.IGNORECASE,
)

# Padrões Jurídicos / Empresariais Adicionais
JUCEG_NIRE_PATTERN = re.compile(r'\b[1-5]\d{10}\b') # Padrão nacional de NIRE
OAB_PATTERN = re.compile(r'\bOAB[/-]?\s*[A-Z]{2}\s*\d+\b', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Filtro de Relevância (A "Peneira" para a IA Relacional)
# ---------------------------------------------------------------------------
PALAVRAS_CHAVE_QUALIFICACAO = re.compile(
    r'\b(residente|domiciliado|casado|cônjuge|filho de|portador da cédula|'
    r'inscrita no CNPJ|com sede|representad|administrador|procurador|'
    r'outorgante|sóci|capital social|quotas|nascido)\b',
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def normalize_cnpj(raw: str) -> str:
    return re.sub(r'\D', '', raw)

def normalize_cpf(raw: str) -> str:
    return re.sub(r'\D', '', raw)

def normalize_cep(raw: str) -> str:
    return re.sub(r'\D', '', raw)

def normalize_telefone(ddd: str, parte1: str, parte2: str) -> str:
    return f"({ddd}) {parte1}-{parte2}"

# ---------------------------------------------------------------------------
# Validação de dígito verificador
# ---------------------------------------------------------------------------

def cpf_valido(cpf: str) -> bool:
    digits = normalize_cpf(cpf)
    if len(digits) != 11: return False
    if len(set(digits)) == 1: return False
    soma = sum(int(d) * (10 - i) for i, d in enumerate(digits[:9]))
    resto = (soma * 10) % 11
    if resto == 10: resto = 0
    if resto != int(digits[9]): return False
    soma = sum(int(d) * (11 - i) for i, d in enumerate(digits[:10]))
    resto = (soma * 10) % 11
    if resto == 10: resto = 0
    if resto != int(digits[10]): return False
    return True

def cnpj_valido(cnpj: str) -> bool:
    digits = normalize_cnpj(cnpj)
    if len(digits) != 14: return False
    if len(set(digits)) == 1: return False
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(d) * p for d, p in zip(digits[:12], pesos))
    resto = soma % 11
    d1 = 0 if resto < 2 else 11 - resto
    if d1 != int(digits[12]): return False
    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(d) * p for d, p in zip(digits[:13], pesos))
    resto = soma % 11
    d2 = 0 if resto < 2 else 11 - resto
    if d2 != int(digits[13]): return False
    return True

# ---------------------------------------------------------------------------
# Formatação de saída
# ---------------------------------------------------------------------------

def format_cpf(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

def format_cnpj(digits: str) -> str:
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

def format_cep(digits: str) -> str:
    return f"{digits[:5]}-{digits[5:]}"