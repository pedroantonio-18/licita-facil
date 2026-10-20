"""
Detector de tipo de PDF e pipeline de ingestão.

Responsável por:
1. Identificar se cada página tem texto extraível ou é imagem
2. Extrair texto de páginas pesquisáveis via PyMuPDF
3. Acionar OCR (docTR) para páginas digitalizadas

A granularidade é por página — um mesmo PDF pode ter
páginas pesquisáveis e páginas digitalizadas.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger("data_crossing.ingestion.detector")

# Mínimo de caracteres por página para considerá-la pesquisável
LIMIAR_CHARS_PAGINA = 50


class TipoPagina(str, Enum):
    PESQUISAVEL = "pesquisavel"
    DIGITALIZADA = "digitalizada"


@dataclass
class Pagina:
    """
    Representa uma página processada com seu conteúdo e metadados.

    O campo `texto` contém o conteúdo extraído independente do método —
    quem recebe uma Pagina não precisa saber se veio de texto direto ou OCR.
    """
    numero: int              # 1-based
    tipo: TipoPagina
    texto: str
    chars: int
    metodo: str              # "pymupdf" | "ocr_doctr"
    confianca: float = 1.0   # 1.0 para pesquisável, < 1.0 para OCR


@dataclass
class DocumentoIngerido:
    """
    Resultado completo da ingestão de um PDF.

    Contém todas as páginas processadas e metadados
    do documento para rastreabilidade.
    """
    nome_arquivo: str
    hash_sha256: str
    total_paginas: int
    paginas: list[Pagina]
    paginas_pesquisaveis: int
    paginas_digitalizadas: int

    def texto_por_pagina(self) -> list[tuple[int, str]]:
        """Retorna lista de (num_pagina, texto) para o extrator."""
        return [(p.numero, p.texto) for p in self.paginas if p.texto.strip()]


def ingerir_pdf(caminho: str, usar_ocr: bool = True) -> DocumentoIngerido:
    """
    Ingere um PDF e retorna todas as páginas processadas.

    Args:
        caminho: caminho do arquivo PDF
        usar_ocr: se True, aplica OCR nas páginas digitalizadas

    Returns:
        DocumentoIngerido com todas as páginas e metadados
    """
    import hashlib

    # Calcula hash para integridade do documento
    with open(caminho, "rb") as f:
        conteudo = f.read()
    hash_sha256 = hashlib.sha256(conteudo).hexdigest()

    doc = fitz.open(caminho)
    nome_arquivo = caminho.split("/")[-1]
    paginas: list[Pagina] = []

    for i, pagina_fitz in enumerate(doc):
        num = i + 1
        texto = pagina_fitz.get_text().strip()
        chars = len(texto)

        if chars >= LIMIAR_CHARS_PAGINA:
            # Página pesquisável — usa o texto direto
            paginas.append(Pagina(
                numero=num,
                tipo=TipoPagina.PESQUISAVEL,
                texto=texto,
                chars=chars,
                metodo="pymupdf",
                confianca=1.0,
            ))
        else:
            # Página digitalizada
            if usar_ocr:
                texto_ocr, confianca = _ocr_pagina(pagina_fitz, num)
                paginas.append(Pagina(
                    numero=num,
                    tipo=TipoPagina.DIGITALIZADA,
                    texto=texto_ocr,
                    chars=len(texto_ocr),
                    metodo="ocr_doctr",
                    confianca=confianca,
                ))
            else:
                paginas.append(Pagina(
                    numero=num,
                    tipo=TipoPagina.DIGITALIZADA,
                    texto="",
                    chars=0,
                    metodo="sem_ocr",
                    confianca=0.0,
                ))
                logger.warning(f"Página {num} de '{nome_arquivo}' é digitalizada e OCR está desativado.")

    doc.close()

    pesquisaveis = sum(1 for p in paginas if p.tipo == TipoPagina.PESQUISAVEL)
    digitalizadas = sum(1 for p in paginas if p.tipo == TipoPagina.DIGITALIZADA)

    logger.info(
        f"'{nome_arquivo}' ingerido: {len(paginas)} páginas "
        f"({pesquisaveis} pesquisáveis, {digitalizadas} digitalizadas)"
    )

    return DocumentoIngerido(
        nome_arquivo=nome_arquivo,
        hash_sha256=hash_sha256,
        total_paginas=len(paginas),
        paginas=paginas,
        paginas_pesquisaveis=pesquisaveis,
        paginas_digitalizadas=digitalizadas,
    )


def _ocr_pagina(pagina_fitz: fitz.Page, num: int) -> tuple[str, float]:
    """
    Aplica OCR em uma página digitalizada usando docTR.

    Returns:
        Tupla (texto_extraído, confiança_média)
    """
    try:
        from doctr.models import ocr_predictor
        from pdf2image import convert_from_path
        import numpy as np

        # Renderiza a página como imagem em alta resolução
        mat = fitz.Matrix(600 / 72, 600 / 72)  # 600 DPI
        pix = pagina_fitz.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")

        # Converte para numpy array para o docTR
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        img_np = np.array(img)

        # Carrega modelo e executa OCR
        model = _get_ocr_model()
        resultado = model([img_np])

        # Extrai texto e calcula confiança média
        linhas = []
        confidencias = []
        for bloco in resultado.pages[0].blocks:
            for linha in bloco.lines:
                palavras = [w.value for w in linha.words]
                confs = [w.confidence for w in linha.words]
                if palavras:
                    linhas.append(" ".join(palavras))
                    confidencias.extend(confs)

        texto = "\n".join(linhas)
        confianca = sum(confidencias) / len(confidencias) if confidencias else 0.0

        return texto, round(confianca, 3)

    except Exception as e:
        logger.error(f"Erro no OCR da página {num}: {e}")
        return "", 0.0


# Singleton do modelo OCR para não recarregar a cada página
_ocr_model = None

def _get_ocr_model():
    """Carrega o modelo docTR uma única vez e reutiliza."""
    global _ocr_model
    if _ocr_model is None:
        from doctr.models import ocr_predictor
        _ocr_model = ocr_predictor(pretrained=True)
        logger.info("Modelo docTR carregado.")
    return _ocr_model
