"""
Gerador de relatório PDF auditável.

O relatório usa linguagem objetiva e não conclusiva, adequada
para uso institucional na Justiça Federal e para anexar ao SEI.

Expressões evitadas: "houve conluio", "ficou comprovado", "a IA identificou".
Expressões usadas: "foi localizada coincidência", "há sobreposição",
"o achado deve ser submetido à análise do servidor responsável".

Estrutura:
  1. Empresas analisadas e dados extraídos
  2. Achados objetivos (regras R01–R08)
  3. Triagem por prioridade
  4. Parecer preliminar de IA (somente se houver)
  Anexo. Dados desconsiderados e avisos de extração
"""

import io
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)

AZUL = colors.HexColor("#1a3a5c")
CINZA_CLARO = colors.HexColor("#f0f4f8")
GRADE = colors.HexColor("#cccccc")

ROTULO_PRIORIDADE = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
COR_PRIORIDADE = {
    "alta": colors.HexColor("#f6d5d5"),
    "media": colors.HexColor("#fbecc9"),
    "baixa": colors.HexColor("#e3ecf5"),
}


# ---------------------------------------------------------------------------
# Estilos e utilitários
# ---------------------------------------------------------------------------

def _estilos():
    styles = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("Titulo", parent=styles["Heading1"], fontSize=14, spaceAfter=6, textColor=AZUL),
        "secao": ParagraphStyle("Secao", parent=styles["Heading2"], fontSize=11, spaceBefore=12, spaceAfter=4, textColor=AZUL),
        "subsecao": ParagraphStyle("Subsecao", parent=styles["Heading3"], fontSize=9.5, spaceBefore=8, spaceAfter=3, textColor=AZUL),
        "corpo": ParagraphStyle("Corpo", parent=styles["Normal"], fontSize=9, spaceAfter=4, leading=14),
        "aviso": ParagraphStyle("Aviso", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#7a0000"), spaceAfter=4, leading=12),
        "campo": ParagraphStyle("Campo", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#555555"), leading=11),
        "celula": ParagraphStyle("Celula", parent=styles["Normal"], fontSize=8, leading=10.5),
        "ia": ParagraphStyle(
            "IA", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=colors.HexColor("#4a3500"),
            backColor=colors.HexColor("#fff6dc"), borderColor=colors.HexColor("#d9b44a"),
            borderWidth=0.6, borderPadding=6, spaceBefore=4, spaceAfter=8,
        ),
    }


def _t(valor) -> str:
    """Texto seguro para Paragraph (o ReportLab interpreta <, > e &)."""
    if valor is None or valor == "":
        return "—"
    return escape(str(valor))


def _data_br(iso: str | None) -> str | None:
    """2026-10-20T11:40:05 → 20/10/2026 às 11:40"""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y às %H:%M")
    except (TypeError, ValueError):
        return iso


def _formatar_cnpj(digitos: str) -> str:
    d = re.sub(r"\D", "", digitos or "")
    if len(d) != 14:
        return digitos or "—"
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _tabela(linhas, larguras, cabecalho=True, extra_estilo=None):
    tab = Table(linhas, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilo = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, GRADE),
        ("PADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if cabecalho:
        estilo += [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CINZA_CLARO]),
        ]
    tab.setStyle(TableStyle(estilo + (extra_estilo or [])))
    return tab


def _cab(texto, e):
    return Paragraph(f"<font color='white'><b>{texto}</b></font>", e["celula"])


def _lista_valores(campos: list[dict]) -> str:
    vistos = []
    for c in campos:
        v = c.get("valor_formatado") or c.get("valor")
        if v and v not in vistos:
            vistos.append(v)
    return ", ".join(_t(v) for v in vistos) if vistos else "Nenhum localizado"


# ---------------------------------------------------------------------------
# Seções
# ---------------------------------------------------------------------------

def _secao_empresas(sessao, e):
    el = [Paragraph("1. Empresas analisadas e dados extraídos", e["secao"])]
    empresas = sessao.get("empresas", [])

    linhas = [[_cab("Razão social", e), _cab("CNPJ", e), _cab("Origem dos dados", e), _cab("Documentos", e)]]
    for emp in empresas:
        docs = [d for d in emp.get("documentos", []) if d.get("arquivo") != "gemini"]
        linhas.append([
            Paragraph(_t(emp["nome"]), e["celula"]),
            Paragraph(_t(_formatar_cnpj(emp.get("cnpj_principal"))), e["celula"]),
            Paragraph(_t(emp.get("origem", "—")), e["celula"]),
            Paragraph(_t(", ".join(d["arquivo"] for d in docs) or "—"), e["celula"]),
        ])
    el.append(_tabela(linhas, [6 * cm, 3.4 * cm, 3.2 * cm, 3.4 * cm]))

    for i, emp in enumerate(empresas, 1):
        bloco = [Paragraph(f"1.{i}. [E{i}] {_t(emp['nome'])}", e["subsecao"])]
        linhas = [
            [Paragraph("<b>CNPJs</b>", e["celula"]), Paragraph(_lista_valores(emp.get("cnpjs", [])), e["celula"])],
            [Paragraph("<b>CPFs</b>", e["celula"]), Paragraph(_lista_valores(emp.get("cpfs", [])), e["celula"])],
            [Paragraph("<b>CEPs</b>", e["celula"]), Paragraph(_lista_valores(emp.get("ceps", [])), e["celula"])],
            [Paragraph("<b>Telefones</b>", e["celula"]), Paragraph(_lista_valores(emp.get("telefones", [])), e["celula"])],
            [Paragraph("<b>Endereços</b>", e["celula"]), Paragraph(
                "<br/>".join(
                    f"[E{i}.L{j}] {_t(end['valor'])}" for j, end in enumerate(emp.get("enderecos", []), 1)
                ) or "Nenhum localizado", e["celula"])],
        ]
        bloco.append(_tabela(linhas, [3 * cm, 13 * cm], cabecalho=False,
                             extra_estilo=[("BACKGROUND", (0, 0), (0, -1), CINZA_CLARO)]))

        pessoas = emp.get("pessoas", [])
        if pessoas:
            linhas = [[_cab("Ref.", e), _cab("Pessoa", e), _cab("CPF", e), _cab("Função", e), _cab("Cônjuge", e)]]
            for j, p in enumerate(pessoas, 1):
                linhas.append([
                    Paragraph(f"E{i}.P{j}", e["celula"]),
                    Paragraph(_t(p.get("nome")), e["celula"]),
                    Paragraph(_t(p.get("cpf")), e["celula"]),
                    Paragraph(_t(p.get("funcao")), e["celula"]),
                    Paragraph(_t(p.get("conjuge")), e["celula"]),
                ])
            bloco.append(Spacer(1, 0.15 * cm))
            bloco.append(_tabela(linhas, [1.4 * cm, 4.8 * cm, 2.8 * cm, 4 * cm, 3 * cm]))
        else:
            bloco.append(Paragraph("Nenhuma pessoa física extraída.", e["campo"]))
        el.append(KeepTogether(bloco[:2]))
        el.extend(bloco[2:])
    return el


def _secao_achados(achados, e):
    el = [Paragraph(f"2. Achados objetivos do cruzamento ({len(achados)} registros)", e["secao"])]
    el.append(Paragraph(
        "Cada achado registra uma coincidência de dados entre duas empresas, apurada por regra "
        "determinística (R01 a R08). O identificador (A001, A002...) é usado para referência "
        "na triagem e no parecer.",
        e["campo"],
    ))

    if not achados:
        el.append(Paragraph(
            "Não foram localizadas coincidências ou sobreposições de dados entre as empresas analisadas "
            "com base nas regras aplicadas.",
            e["corpo"],
        ))
        return el

    for achado in achados:
        linhas = [
            [Paragraph("Empresa A", e["campo"]), Paragraph(_t(achado["empresa_a"]), e["celula"])],
            [Paragraph("Empresa B", e["campo"]), Paragraph(_t(achado["empresa_b"]), e["celula"])],
            [Paragraph("Campo", e["campo"]), Paragraph(_t(achado["campo"]), e["celula"])],
            [Paragraph("Valor", e["campo"]), Paragraph(_t(achado["valor"]), e["celula"])],
            [Paragraph("Similaridade", e["campo"]), Paragraph(f"{achado['similaridade'] * 100:.0f}%", e["celula"])],
            [Paragraph("Prioridade de triagem", e["campo"]), Paragraph(ROTULO_PRIORIDADE.get(achado.get("prioridade"), "—"), e["celula"])],
        ]
        for lado, chave in (("A", "evidencia_a"), ("B", "evidencia_b")):
            ev = achado.get(chave) or {}
            if ev.get("pagina"):
                linhas.append([Paragraph(f"Origem ({lado}) — Página", e["campo"]), Paragraph(_t(ev["pagina"]), e["celula"])])
            if ev.get("trecho"):
                linhas.append([Paragraph(f"Origem ({lado}) — Trecho", e["campo"]), Paragraph(_t(ev["trecho"][:200]), e["celula"])])
            if ev.get("funcao"):
                linhas.append([Paragraph(f"Origem ({lado}) — Função", e["campo"]), Paragraph(_t(ev["funcao"]), e["celula"])])

        bloco = [
            Spacer(1, 0.2 * cm),
            Paragraph(
                f"Achado {achado['id']} — Regra {achado['regra_codigo']}: {_t(achado['regra_descricao'])}",
                e["subsecao"],
            ),
            _tabela(linhas, [4.5 * cm, 11.5 * cm], cabecalho=False,
                    extra_estilo=[("BACKGROUND", (0, 0), (0, -1), CINZA_CLARO)]),
        ]
        if achado.get("nota"):
            bloco.append(Paragraph(f"Nota: {_t(achado['nota'])}", e["aviso"]))
        el.append(KeepTogether(bloco))
    return el


def _secao_triagem(achados, e):
    el = [Paragraph("3. Triagem por prioridade", e["secao"])]
    if not achados:
        el.append(Paragraph("Sem achados a triar.", e["corpo"]))
        return el

    el.append(Paragraph(
        "A prioridade apenas ordena a verificação pelo servidor, segundo o quanto o dado coincidente "
        "identifica pessoa ou vínculo específico: Alta (mesmo CPF; mesma pessoa na mesma função; "
        "vínculo familiar), Média (mesmo CNPJ de terceiro, telefone, nome similar ou endereço), "
        "Baixa (mesmo CEP). "
        "Não representa juízo sobre a conduta das empresas.",
        e["campo"],
    ))

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    ordenados = sorted(achados, key=lambda a: (ordem.get(a.get("prioridade"), 9), a["id"]))
    contagem = {p: sum(1 for a in achados if a.get("prioridade") == p) for p in ordem}
    el.append(Paragraph(
        " · ".join(f"{ROTULO_PRIORIDADE[p]}: {n}" for p, n in contagem.items()),
        e["corpo"],
    ))

    linhas = [[_cab("Prioridade", e), _cab("Achado", e), _cab("Regra", e), _cab("Empresas", e), _cab("Valor", e)]]
    estilo_cores = []
    for i, a in enumerate(ordenados, 1):
        linhas.append([
            Paragraph(ROTULO_PRIORIDADE.get(a.get("prioridade"), "—"), e["celula"]),
            Paragraph(a["id"], e["celula"]),
            Paragraph(a["regra_codigo"], e["celula"]),
            Paragraph(f"{_t(a['empresa_a'])} × {_t(a['empresa_b'])}", e["celula"]),
            Paragraph(_t(a["valor"]), e["celula"]),
        ])
        cor = COR_PRIORIDADE.get(a.get("prioridade"))
        if cor:
            estilo_cores.append(("BACKGROUND", (0, i), (0, i), cor))
    el.append(_tabela(linhas, [2 * cm, 1.6 * cm, 1.4 * cm, 6.5 * cm, 4.5 * cm], extra_estilo=estilo_cores))
    return el


def _secao_parecer(parecer, e):
    el = [Paragraph("4. Parecer preliminar gerado por inteligência artificial", e["secao"])]
    el.append(Paragraph(
        "<b>CONTEÚDO GERADO POR INTELIGÊNCIA ARTIFICIAL — OPINIÃO PRELIMINAR E PARCIAL, NÃO VINCULANTE.</b> "
        f"Modelo: {_t(parecer.get('modelo') or 'não informado')}. "
        f"Gerado em: {_t(_data_br(parecer.get('gerado_em')))}. "
        "Cada afirmação foi validada automaticamente: só foram mantidas as que citam achados ou dados "
        "existentes deste relatório e que não usam linguagem conclusiva. As referências E1, E1.P2 etc. "
        "remetem à empresa e à pessoa de mesma ordem na seção 1. O texto não substitui a análise do "
        "servidor competente.",
        e["ia"],
    ))

    el.append(Paragraph("4.1. Avaliação geral", e["subsecao"]))
    avaliacao = parecer.get("avaliacao_geral")
    if avaliacao:
        el.append(Paragraph(f"<b>{_t(avaliacao['conclusao'])}</b>", e["corpo"]))
        refs = ", ".join(avaliacao.get("referencias", []))
        el.append(Paragraph(
            f"Fundamentação{f' [{_t(refs)}]' if refs else ''}: {_t(avaliacao['fundamentacao'])}",
            e["corpo"],
        ))
        el.append(Paragraph(_t(avaliacao["ressalva"]), e["campo"]))
    else:
        el.append(Paragraph(
            "Não há avaliação geral: a resposta do modelo não passou na validação automática "
            "(ver itens descartados abaixo).",
            e["corpo"],
        ))

    el.append(Paragraph("4.2. Comentários sobre os achados e dados", e["subsecao"]))
    aceitos = parecer.get("aceitos", [])
    if aceitos:
        for i, item in enumerate(aceitos, 1):
            refs = ", ".join(item.get("achados", []))
            el.append(Paragraph(f"4.2.{i}. [{_t(refs)}] {_t(item['texto'])}", e["corpo"]))
    else:
        el.append(Paragraph("Nenhum comentário aprovado na validação automática.", e["campo"]))

    descartados = parecer.get("descartados", [])
    el.append(Paragraph(f"Itens descartados pela validação automática ({len(descartados)})", e["subsecao"]))
    if descartados:
        linhas = [[_cab("Texto descartado", e), _cab("Referências citadas", e), _cab("Motivo", e)]]
        for d in descartados:
            linhas.append([
                Paragraph(_t(d.get("texto", "")[:400]), e["celula"]),
                Paragraph(_t(", ".join(d.get("achados", [])) or "—"), e["celula"]),
                Paragraph(_t(d.get("motivo")), e["celula"]),
            ])
        el.append(_tabela(linhas, [8.5 * cm, 2.5 * cm, 5 * cm]))
    else:
        el.append(Paragraph("Nenhum item descartado.", e["campo"]))
    return el


def _secao_anexo(sessao, e):
    el = [Paragraph("Anexo — Dados desconsiderados e avisos de extração", e["secao"])]
    desconsiderados = sessao.get("desconsiderados", [])
    el.append(Paragraph(
        "Valores localizados nos documentos, mas excluídos do cruzamento por não se referirem às "
        "empresas licitantes (ex.: usuário consultante do SICAF, órgãos de registro). "
        "A exclusão é registrada para conferência.",
        e["campo"],
    ))
    if desconsiderados:
        linhas = [[_cab("Empresa", e), _cab("Tipo", e), _cab("Valor", e), _cab("Motivo", e)]]
        for d in desconsiderados:
            linhas.append([
                Paragraph(_t(d.get("empresa")), e["celula"]),
                Paragraph(_t(d.get("tipo")), e["celula"]),
                Paragraph(_t(d.get("valor_formatado") or d.get("valor")), e["celula"]),
                Paragraph(_t(d.get("motivo")), e["celula"]),
            ])
        el.append(_tabela(linhas, [4.5 * cm, 1.5 * cm, 4 * cm, 6 * cm]))
    else:
        el.append(Paragraph("Nenhum valor desconsiderado.", e["corpo"]))

    avisos = [(emp["nome"], a) for emp in sessao.get("empresas", []) for a in emp.get("avisos", [])]
    el.append(Paragraph("Avisos de extração", e["subsecao"]))
    if avisos:
        for nome, aviso in avisos:
            el.append(Paragraph(f"{_t(nome)}: {_t(aviso)}", e["aviso"]))
    else:
        el.append(Paragraph("Nenhum aviso.", e["campo"]))
    return el


# ---------------------------------------------------------------------------
# Gerador principal
# ---------------------------------------------------------------------------

def gerar_pdf_relatorio(processo_id: str, sessao: dict) -> bytes:
    """
    Gera o relatório em bytes PDF.

    Args:
        processo_id: identificador do processo
        sessao: dicionário com empresas, achados, desconsiderados e (opcional) parecer

    Returns:
        Bytes do PDF gerado
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title=f"Relatório de análise documental — {processo_id}",
        author="LicitaFácil Data Crossing",
    )

    e = _estilos()
    elementos = []
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    achados = sessao.get("achados", [])

    # Cabeçalho
    elementos.append(Paragraph("JUSTIÇA FEDERAL", e["titulo"]))
    elementos.append(Paragraph("Sistema de Análise Documental — LicitaFácil", e["corpo"]))
    elementos.append(HRFlowable(width="100%", thickness=1, color=AZUL))
    elementos.append(Spacer(1, 0.3 * cm))

    elementos.append(Paragraph("RELATÓRIO DE ANÁLISE DOCUMENTAL", e["titulo"]))
    elementos.append(Paragraph(f"Processo: {_t(processo_id)}", e["corpo"]))
    elementos.append(Paragraph(f"Gerado em: {agora}", e["corpo"]))
    elementos.append(Paragraph(
        f"Empresas analisadas: {len(sessao.get('empresas', []))} · Achados: {len(achados)}",
        e["corpo"],
    ))
    elementos.append(Spacer(1, 0.3 * cm))

    # Aviso obrigatório
    elementos.append(Paragraph(
        "<b>AVISO:</b> Este relatório é produto de extração e cruzamento automatizado de dados. "
        "Não constitui juízo de valor, conclusão jurídica ou afirmação de irregularidade. "
        "A análise das informações aqui consignadas é de competência exclusiva do servidor responsável.",
        e["aviso"],
    ))
    elementos.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))

    elementos.extend(_secao_empresas(sessao, e))
    elementos.extend(_secao_achados(achados, e))
    elementos.extend(_secao_triagem(achados, e))
    if sessao.get("parecer"):
        elementos.extend(_secao_parecer(sessao["parecer"], e))
    elementos.extend(_secao_anexo(sessao, e))

    # Rodapé técnico
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elementos.append(Paragraph(
        f"Relatório gerado pelo sistema LicitaFácil Data Crossing v0.1.0 em {agora}. "
        "Os dados apresentados são resultado de extração automatizada e de cruzamento por regras determinísticas. "
        "O hash SHA-256 deste arquivo é registrado no momento da emissão para conferência de integridade. "
        "Toda interpretação jurídica é de responsabilidade do servidor competente.",
        e["campo"],
    ))

    def _numerar(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2.5 * cm, 1.5 * cm, f"Processo {processo_id} — LicitaFácil")
        canvas.drawRightString(A4[0] - 2.5 * cm, 1.5 * cm, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=_numerar, onLaterPages=_numerar)
    buffer.seek(0)
    return buffer.read()
