"""
Minuta em HTML para copiar e colar no editor do SEI.

Teste de colagem feito pela SELIT no SEI do TRF1 (05/11/2026): a formatação direta passa
(negrito, itálico, sublinhado, alinhamento, recuo da primeira linha, tabela com borda,
fundo amarelo, cor); o SEI do TRF1 não tem estilos de numeração automática. Por isso:
- a numeração vai escrita no próprio texto ("1.1.", "2.3.4."), já refeita pelo sistema;
- a formatação vai em estilo direto (style=...), com a classe do SEI equivalente junto;
- fonte Times New Roman 12, a mesma das minutas publicadas pela SJGO;
- o que ficou pendente vai com fundo amarelo, para não passar despercebido no SEI.
"""

from __future__ import annotations

from html import escape

from app.montagem import MARCADOR_PRETO, BlocoFinal, Minuta

FONTE = "font-family: 'Times New Roman', Times, serif; font-size: 12pt;"
AMARELO = "background-color: #ffff00;"


def _trechos_html(bloco: BlocoFinal, pendentes: set[str]) -> str:
    partes = []
    for t in bloco.trechos:
        texto = escape(t.texto).replace("\n", "<br>")
        if t.negrito:
            texto = f"<b>{texto}</b>"
        if t.italico and not t.variavel:
            texto = f"<i>{texto}</i>"
        if t.sublinhado:
            texto = f"<u>{texto}</u>"
        if t.variavel and t.texto.strip() and bloco.id in pendentes:
            texto = f'<span style="{AMARELO}">{texto}</span>'
        elif bloco.id in pendentes:
            texto = MARCADOR_PRETO.sub(lambda m: f'<span style="{AMARELO}">{m.group(0)}</span>', texto)
        partes.append(texto)
    return "".join(partes)


def _paragrafo(classe: str, estilo: str, conteudo: str) -> str:
    return f'<p class="{classe}" style="{FONTE} {estilo}">{conteudo}</p>'


def _bloco_html(b: BlocoFinal, pendentes: set[str]) -> str:
    if b.tipo == "tabela":
        linhas = []
        for i, linha in enumerate(b.linhas):
            celulas = "".join(
                f'<td style="border: 1px solid #000; padding: 2px 6px;">'
                f'<p class="Tabela_Texto_Centralizado" style="{FONTE} text-align: center; margin: 0;">'
                f'{"<b>" if i == 0 else ""}{escape(c)}{"</b>" if i == 0 else ""}</p></td>'
                for c in linha)
            linhas.append(f"<tr>{celulas}</tr>")
        return ('<table style="border-collapse: collapse; margin: 6pt auto;" border="1">'
                + "".join(linhas) + "</table>")

    conteudo = _trechos_html(b, pendentes)
    destaque = AMARELO if b.id in pendentes and b.trechos and all(t.variavel for t in b.trechos if t.texto.strip()) else ""
    if b.tipo == "titulo":
        return _paragrafo("Texto_Alinhado_Esquerda", f"text-align: left; font-weight: bold; {destaque}",
                          f"{escape(b.numero)}&nbsp;&nbsp;{conteudo}")
    if b.tipo == "item":
        return _paragrafo("Texto_Justificado", f"text-align: justify; {destaque}", f"{escape(b.numero)}&nbsp;&nbsp;{conteudo}")
    if b.alinhamento == "center":
        return _paragrafo("Texto_Centralizado", f"text-align: center; {destaque}", conteudo)
    if b.alinhamento == "right":
        return _paragrafo("Texto_Alinhado_Direita", f"text-align: right; {destaque}", conteudo)
    return _paragrafo("Texto_Justificado", f"text-align: justify; {destaque}", conteudo)


def _sumario(minuta: Minuta) -> str:
    linhas = [_paragrafo("Texto_Centralizado", "text-align: center; font-weight: bold;", "Sumário")]
    for t in minuta.titulos:
        linhas.append(_paragrafo("Texto_Alinhado_Esquerda", "text-align: left;", f"{escape(t.numero)}&nbsp;&nbsp;{escape(t.texto.strip())}"))
    return "".join(linhas)


def html_sei(minuta: Minuta) -> str:
    """Trecho HTML pronto para copiar (seleção) e colar no editor do SEI."""
    pendentes = {p.bloco for p in minuta.pendencias}
    partes = []
    for b in minuta.blocos:
        if b.id == minuta.sumario_antes:
            partes.append(_sumario(minuta))
        partes.append(_bloco_html(b, pendentes))
    return "\n".join(partes)
