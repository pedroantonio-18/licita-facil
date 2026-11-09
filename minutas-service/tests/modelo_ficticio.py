"""
Gera um .docx mínimo no formato dos modelos da AGU, para os testes não dependerem
dos arquivos baixados (estilos "Nivel 01/2/3", "ou", texto vermelho, realces, notas).
"""

import io
import zipfile
from xml.sax.saxutils import escape

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def run(texto, vermelho=False, realce=None, negrito=False):
    props = ""
    if negrito:
        props += "<w:b/>"
    if vermelho:
        props += '<w:i/><w:color w:val="FF0000"/>'
    if realce:
        props += f'<w:highlight w:val="{realce}"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


def par(*runs, estilo=None, nota=None, sem_numero=False, alinhamento=None):
    ppr = ""
    if estilo or sem_numero or alinhamento:
        ppr = "<w:pPr>"
        if estilo:
            ppr += f'<w:pStyle w:val="{estilo}"/>'
        if sem_numero:
            ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'
        if alinhamento:
            ppr += f'<w:jc w:val="{alinhamento}"/>'
        ppr += "</w:pPr>"
    corpo = "".join(r if r.startswith("<w:r>") else run(r) for r in runs)
    if nota is not None:
        corpo = f'<w:commentRangeStart w:id="{nota}"/>{corpo}<w:commentRangeEnd w:id="{nota}"/>' \
                f'<w:r><w:commentReference w:id="{nota}"/></w:r>'
    return f"<w:p>{ppr}{corpo}</w:p>"


ESTILOS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {NS}>
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Nivel01"><w:name w:val="Nivel 01"/><w:basedOn w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Nivel2"><w:name w:val="Nivel 2"/><w:basedOn w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Nivel3"><w:name w:val="Nivel 3"/><w:basedOn w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Nvel2-Opcional"><w:name w:val="Nível 2-Opcional"/><w:basedOn w:val="Nivel2"/></w:style>
  <w:style w:type="paragraph" w:styleId="Nvel3-R"><w:name w:val="Nível 3-R"/><w:basedOn w:val="Nivel3"/></w:style>
  <w:style w:type="paragraph" w:styleId="ou"><w:name w:val="ou"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>"""

NOTAS = {
    "0": "ORIENTAÇÕES PARA USO DO MODELO – LEITURA OBRIGATÓRIA. Texto geral do modelo fictício.",
    "1": "Nota explicativa: adotar somente se houver registro de preços.",
    "2": "Nota explicativa: escolher uma das redações.",
}


def documento(corpo: list[str] | None = None) -> str:
    corpo = corpo or [
        par(run("ÓRGÃO OU ENTIDADE PÚBLICA", vermelho=True), nota="0"),
        par("AVISO DE CONTRATAÇÃO DIRETA Nº ", run("[XX/AAAA]", vermelho=True)),
        par("Torna-se público que o(a) ", run("[órgão]", vermelho=True), " realizará Dispensa Eletrônica.",
            estilo="Nivel2", sem_numero=True),
        par("DO OBJETO", estilo="Nivel01"),                                                     # 1.
        par("O objeto é a contratação de ", run("[objeto]", vermelho=True), ".", estilo="Nivel2"),   # 1.1.
        par("Havendo mais de um item, o fornecedor participa de quantos quiser.", estilo="Nivel3"),  # 1.1.1.
        par("DO REGISTRO DE PREÇOS", estilo="Nivel01", nota="1"),                               # 2. (RP)
        par(run("As regras do registro de preços constam da ata.", realce="cyan"), estilo="Nivel2"),  # 2.1.
        par("DA PARTICIPAÇÃO", estilo="Nivel01"),                                               # 3.
        par("Não poderão participar:", estilo="Nivel2"),                                        # 3.1.
        par("empresas suspensas;", estilo="Nivel3"),                                            # 3.1.1.
        par("pessoas físicas.", estilo="Nvel3-R"),                                              # 3.1.2.
        par("O impedimento de que trata o item 3.1.1 vale para o substituto.", estilo="Nivel2"),  # 3.2.
        par("Os itens 3.1.1 e 3.1.2 não impedem a contratação", run(" nem a adesão à ata de registro de preços", realce="cyan"),
            ".", estilo="Nivel2"),                                                              # 3.3.
        par("A licitação será dividida em itens.", estilo="Nivel2", nota="2"),                  # 3.4.
        par("OU", estilo="ou"),
        par("A licitação será realizada em item único.", estilo="Nivel2"),                     # 3.5.
        par("DAS DISPOSIÇÕES GERAIS", estilo="Nivel01"),                                        # 4.
        par("Ver item 2.1 sobre a ata.", estilo="Nivel2"),                                      # 4.1.
    ]
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(corpo)}</w:body></w:document>'


def comentarios() -> str:
    itens = "".join(f'<w:comment w:id="{i}" w:author="AGU"><w:p><w:r><w:t>{escape(t)}</w:t></w:r></w:p></w:comment>'
                    for i, t in NOTAS.items())
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments {NS}>{itens}</w:comments>'


RODAPE = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p>'
          '<w:r><w:t>Modelo fictício de Aviso de Contratação Direta Versão: </w:t></w:r>'
          '<w:r><w:t>MAR/2026</w:t></w:r></w:p></w:ftr>')


def docx(corpo: list[str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", documento(corpo))
        z.writestr("word/styles.xml", ESTILOS)
        z.writestr("word/comments.xml", comentarios())
        z.writestr("word/footer1.xml", RODAPE)
    return buf.getvalue()


def aviso_com_capa() -> bytes:
    """Capa + preâmbulo no formato real do Aviso da AGU (marcadores pretos na capa,
    processo vermelho em pedaços, registro de preços realçado no meio do preâmbulo)."""
    v = lambda t: run(t, vermelho=True)
    rp = lambda t: run(t, realce="cyan")
    return docx([
        par("AVISO DE CONTRATAÇÃO"), par("DIRETA"), par("XXX/XXXX"),
        par("CONTRATANTE/", run("GERENCIADOR", realce="yellow"), " (UASG)"), par("XXXX"),
        par("OBJETO"), par(rp("[registro de preços]")),
        par("VALOR TOTAL DA CONTRATAÇÃO"), par("R$ 00.000,00"),
        par("DATA DA SESSÃO PÚBLICA"), par("De XX/XX/202X"),
        par("CRITÉRIO DE JULGAMENTO:"), par("[menor preço] / [maior desconto] por [item] / [por grupo] / [global]"),
        par(v("ÓRGÃO OU ENTIDADE PÚBLICA")),
        par("AVISO DE CONTRATAÇÃO DIRETA Nº ", v("["), v("XX/AAAA"), v("]")),
        par("(Processo Administrativo n° ", v("xxxxx"), ".", v("xxxxxx"), "/", v("xxxx"), "-", v("xx"), ")"),
        par("Torna-se público que o(a) ", v("["), v("órgão ou entidade pública"), v("]"), ", por meio do(a) ",
            v("[setor responsável pelas contratações]"), ", sediado(a) ", v("[endereço]"), ", realizará Dispensa Eletrônica",
            rp(", para registro de preços"), ", com critério de julgamento ", v("[menor preço]"), v(" OU "), v("[maior desconto]"),
            ", na hipótese do art. 75, ", v("inciso [inciso]"), ", nos termos da Lei nº 14.133, de 2021",
            rp(", do Decreto nº 11.462, de 2023"), ", e demais normas aplicáveis.", estilo="Nivel2", sem_numero=True),
        par("DO OBJETO", estilo="Nivel01"),
        par("O objeto é a contratação de ", v("[objeto]"), ".", estilo="Nivel2"),
        par("O prazo de validade da proposta não será inferior a ", run("XX", vermelho=True, realce="cyan"),
            run(" ", vermelho=True, realce="cyan"), run("(", realce="cyan"),
            run("valor por extenso", vermelho=True, realce="cyan"), run(") dias", realce="cyan"),
            ", a contar da data de sua apresentação.", estilo="Nivel2"),
        par(v("[ASSINATURA DA AUTORIDADE COMPETENTE]")),
    ])
