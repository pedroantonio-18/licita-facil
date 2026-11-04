"""
Montagem dos PDFs para o SEI.

- PDF por bloco temático (como a SELIT junta no SEI), só com os documentos,
  na ordem padrão e comprimido:
    Bloco 1 — Habilitação Jurídica
    Bloco 2 — Regularidade Fiscal, Social e Trabalhista (o SICAF; certidões
              avulsas só para o que o SICAF não cobre)
    Bloco 3 — Idoneidade (TCU e CGU)
    Bloco 4 — Qualificação Econômico-Financeira (falência, quando exigida)
- Relatório de conferência: o checklist de todas as empresas, para o
  servidor conferir antes de juntar.
"""

import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import fitz  # PyMuPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.certidoes import BLOCOS, TIPOS_POR_ID, CertidaoLida
from app.conferencia import ATENCAO, FALTANDO, OK, PROBLEMA, ItemChecklist, Parametros, situacao_geral
from app.texto import formatar_cnpj

AZUL = colors.HexColor("#1a3a5c")
ROTULO_SITUACAO = {OK: "OK", ATENCAO: "Conferir", PROBLEMA: "Problema", FALTANDO: "Faltando"}
COR_SITUACAO = {
    OK: colors.HexColor("#d9f2e4"), ATENCAO: colors.HexColor("#fbecc9"),
    PROBLEMA: colors.HexColor("#f6d5d5"), FALTANDO: colors.HexColor("#f6d5d5"),
}

_st = getSampleStyleSheet()
TITULO = ParagraphStyle("t", parent=_st["Heading1"], fontSize=13, textColor=AZUL, spaceAfter=4)
SUBTITULO = ParagraphStyle("s", parent=_st["Heading2"], fontSize=10.5, textColor=AZUL, spaceBefore=10, spaceAfter=4)
CORPO = ParagraphStyle("c", parent=_st["Normal"], fontSize=9, leading=12.5)
CELULA = ParagraphStyle("ce", parent=_st["Normal"], fontSize=7.5, leading=9.5)
AVISO = ParagraphStyle("a", parent=_st["Normal"], fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))


def _t(v) -> str:
    return escape(str(v)) if v not in (None, "") else "—"


def _data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _cabecalho(processo_id: str, p: Parametros) -> list:
    return [
        Paragraph("JUSTIÇA FEDERAL — Licita Fácil", CORPO),
        Paragraph("Conferência de certidões de habilitação", TITULO),
        Paragraph(f"Processo: {_t(processo_id)} · Data de referência: {_data(p.data_referencia)} · "
                  f"Gerado em: {datetime.now():%d/%m/%Y às %H:%M}", CORPO),
        HRFlowable(width="100%", thickness=0.8, color=AZUL, spaceBefore=4, spaceAfter=6),
    ]


def _tabela_empresa(nome: str, cnpj: str, itens: list[ItemChecklist], arquivos: list[dict]) -> list:
    geral = situacao_geral(itens)
    el = [
        Paragraph(f"{_t(nome)} — CNPJ {formatar_cnpj(cnpj)}", SUBTITULO),
        Paragraph(f"Situação geral: <b>{ROTULO_SITUACAO[geral]}</b>", CORPO),
        Spacer(1, 0.15 * cm),
    ]
    cab = ["Bloco", "Documento", "Situação", "Emissão", "Validade", "Resultado", "Observações"]
    linhas = [[Paragraph(f"<font color='white'><b>{c}</b></font>", CELULA) for c in cab]]
    estilos = []
    for i, item in enumerate(itens, 1):
        cert = next((c.certidao for c in item.conferencias if c.certidao.tipo == item.tipo), None)
        nome_tipo = item.tipo_nome + ("" if item.obrigatoria else " (complementar)")
        detalhes = list(item.observacoes) + (cert.detalhes if cert and item.fonte != "sicaf" else [])
        origem = cert.validade_origem if cert and item.fonte != "sicaf" else ""
        linhas.append([
            Paragraph(str(item.bloco), CELULA),
            Paragraph(_t(nome_tipo), CELULA),
            Paragraph(f"<b>{ROTULO_SITUACAO[item.situacao]}</b>"
                      + ("<br/><font size=6>(conferido pelo servidor)</font>" if item.conferencia_manual else ""), CELULA),
            Paragraph(_data(item.emissao), CELULA),
            Paragraph(_data(item.validade) + (f"<br/><font size=6>{_t(origem)}</font>" if origem else ""), CELULA),
            Paragraph(_t(item.resultado), CELULA),
            Paragraph("<br/>".join(_t(d) for d in detalhes) or "—", CELULA),
        ])
        estilos.append(("BACKGROUND", (2, i), (2, i), COR_SITUACAO[item.situacao]))
    tabela = Table(linhas, colWidths=[1 * cm, 3.6 * cm, 1.7 * cm, 1.7 * cm, 2 * cm, 2.2 * cm, 5.2 * cm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ] + estilos))
    el.append(tabela)

    if arquivos:
        el.append(Spacer(1, 0.2 * cm))
        el.append(Paragraph("Arquivos recebidos para conferência", CORPO))
        linhas = [[Paragraph(f"<font color='white'><b>{c}</b></font>", CELULA) for c in ("Arquivo", "Págs.", "SHA-256")]]
        for a in arquivos:
            linhas.append([Paragraph(_t(a["arquivo"]), CELULA), Paragraph(str(a["paginas"]), CELULA),
                           Paragraph(f"<font size=6>{a['sha256']}</font>", CELULA)])
        t = Table(linhas, colWidths=[6.4 * cm, 1.2 * cm, 9.8 * cm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 2),
        ]))
        el.append(t)
    return el


def _rodape() -> list:
    return [
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Conferência automatizada a partir do texto das certidões. Documentos marcados como "
            "\"Conferir\" ou \"Problema\" devem ser verificados pelo servidor responsável, a quem cabe "
            "a decisão sobre a habilitação. Itens \"conferido pelo servidor\" trazem a justificativa "
            "registrada e a situação originalmente apontada pelo sistema.",
            AVISO,
        ),
    ]


def _construir(elementos: list) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    doc.build(elementos)
    return buffer.getvalue()


def relatorio_conferencia(processo_id: str, p: Parametros,
                          empresas: list[tuple[str, str, list[ItemChecklist], list[dict]]]) -> bytes:
    """Checklist de todas as empresas num PDF só."""
    el = _cabecalho(processo_id, p)
    obrig = ", ".join(TIPOS_POR_ID[t].nome.split(" —")[0].split(" (")[0] for t in p.obrigatorias if t in TIPOS_POR_ID)
    objeto = {"compras": "compra de bens", "servicos": "serviços", "ambos": "bens e serviços"}.get(p.objeto, p.objeto)
    el.append(Paragraph(
        f"Objeto: {objeto}. Itens obrigatórios: {_t(obrig)}. Regularidade comprovada pelo SICAF quando válida "
        f"nele; certidão avulsa só para o que o SICAF não cobre. TCU e CGU válidas por {p.dias_consultas} dias "
        f"da emissão; falência sem validade impressa: {p.dias_falencia} dias. "
        "Blocos: " + "; ".join(f"{n} — {nome}" for n, nome in BLOCOS.items()) + ".", AVISO))
    for nome, cnpj, itens, arquivos in empresas:
        el.extend(_tabela_empresa(nome, cnpj, itens, arquivos))
    el.extend(_rodape())
    return _construir(el)


def documentos_por_bloco(itens: list[ItemChecklist]) -> dict[int, list[CertidaoLida]]:
    """Documentos de cada bloco, na ordem padrão e sem repetir o mesmo trecho de arquivo."""
    blocos: dict[int, list[CertidaoLida]] = {}
    vistos: set[tuple] = set()
    for item in itens:
        documentos = sorted(item.documentos_do_bloco(), key=lambda c: c.emissao or datetime.min.date(), reverse=True)
        for cert in documentos:
            chave = (cert.arquivo, tuple(cert.paginas))
            if chave not in vistos:
                vistos.add(chave)
                blocos.setdefault(item.bloco, []).append(cert)
    return blocos


def pdf_bloco(documentos: list[CertidaoLida], pasta_arquivos: Path) -> bytes:
    """Um PDF único com os documentos do bloco, comprimido, sem folha de rosto."""
    final = fitz.open()
    abertos: dict[str, fitz.Document] = {}
    try:
        for cert in documentos:
            if cert.arquivo not in abertos:
                abertos[cert.arquivo] = fitz.open(pasta_arquivos / cert.arquivo)
            for pagina in cert.paginas:
                final.insert_pdf(abertos[cert.arquivo], from_page=pagina - 1, to_page=pagina - 1)
        return final.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True)
    finally:
        for doc in abertos.values():
            doc.close()
        final.close()
