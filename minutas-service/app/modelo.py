"""
Leitura dos modelos de minuta da AGU (.docx) em blocos estruturados.

Os modelos da AGU seguem uma convenção explicada nas "Orientações para uso do modelo":
- texto em preto: invariável (alterar exige justificativa nos autos);
- texto em vermelho itálico: deve ser preenchido ou escolhido pelo órgão;
- realces coloridos marcam temas que ficam ou saem conforme o caso (registro de preços,
  margem de preferência, mão de obra exclusiva, engenharia); o amarelo só indica
  o que mudou em relação à versão anterior do modelo;
- notas explicativas ficam em comentários do Word e saem da versão final;
- estilos "Nivel 01" a "Nivel 4" definem a numeração (1., 1.1., 1.1.1., ...);
  variantes "-Opcional", "-R", "Misto" são o mesmo nível com conteúdo variável;
- parágrafos com o estilo "ou" separam redações alternativas.

O leitor guarda o texto literalmente: quem monta a minuta final copia daqui o que
não foi alterado, para que nada do modelo mude sem aparecer na revisão.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Realce do Word → tema da AGU (legenda das orientações de uso)
TEMAS = {
    "cyan": "registro_precos",          # turquesa
    "green": "margem_preferencia",      # verde brilhante
    "magenta": "mao_de_obra_exclusiva",  # rosa
    "darkCyan": "engenharia",           # azul-petróleo
}
NOMES_TEMAS = {
    "registro_precos": "Registro de preços",
    "margem_preferencia": "Margem de preferência",
    "mao_de_obra_exclusiva": "Mão de obra com dedicação exclusiva",
    "engenharia": "Obras e serviços de engenharia",
}
# Amarelo = "alterado em relação à versão anterior do modelo": o texto fica, só o realce sai.
REALCE_ATUALIZACAO = {"yellow", "darkYellow"}

_VERMELHOS = {"FF0000", "EE0000", "C00000", "E00000", "FF0101"}


@dataclass
class Trecho:
    texto: str
    variavel: bool = False   # vermelho na AGU: preencher/escolher
    tema: str | None = None  # realce de tema (registro de preços etc.)
    negrito: bool = False
    italico: bool = False
    sublinhado: bool = False
    campo: str | None = None  # id do campo a preencher a que o trecho pertence (ex.: "B035.2")


@dataclass
class Campo:
    id: str             # "B035.2"
    bloco: str
    texto: str          # como está no modelo: "[setor responsável pelas contratações]"
    opcoes: list[str]   # "[menor preço] OU [maior desconto]" → ["menor preço", "maior desconto"]


@dataclass
class Bloco:
    id: str
    tipo: str                   # "titulo" | "item" | "paragrafo" | "ou" | "tabela" | "sumario"
    nivel: int | None = None    # 1..5 para itens numerados
    estilo: str = ""
    opcional: bool = False      # estilo "-Opcional" da AGU
    alinhamento: str = ""       # "center" | "both" | "right" | ""
    trechos: list[Trecho] = field(default_factory=list)
    linhas: list[list[str]] = field(default_factory=list)   # tabelas: células em texto
    notas: list[str] = field(default_factory=list)          # notas explicativas (comentários)

    @property
    def texto(self) -> str:
        if self.tipo == "tabela":
            return "\n".join(" | ".join(c) for c in self.linhas)
        return "".join(t.texto for t in self.trechos)

    @property
    def temas(self) -> set[str]:
        return {t.tema for t in self.trechos if t.tema and t.texto.strip()}

    @property
    def tem_variavel(self) -> bool:
        return any(t.variavel and t.texto.strip() for t in self.trechos)

    @property
    def clausula_vermelha(self) -> bool:
        """Cláusula inteira em vermelho (ex.: regras de mão de obra exclusiva no edital): não é um
        campo a preencher, é uma disposição que se adota ou não conforme o caso."""
        com_texto = [t for t in self.trechos if t.texto.strip()]
        texto = self.texto.strip()
        longo = len(texto) >= 60 or self.tipo == "titulo"     # título todo vermelho = seção opcional
        return bool(com_texto) and all(t.variavel for t in com_texto) and longo and "[" not in texto

    @property
    def campos(self) -> list[Campo]:
        vistos: dict[str, list[str]] = {}
        for t in self.trechos:
            if t.campo:
                vistos.setdefault(t.campo, []).append(t.texto)
        return [Campo(id=c, bloco=self.id, texto="".join(partes).strip(), opcoes=_opcoes("".join(partes)))
                for c, partes in vistos.items()]

    @property
    def tema_integral(self) -> str | None:
        """Tema que cobre todo o texto do bloco (o bloco inteiro sai se o tema não se aplica)."""
        com_texto = [t for t in self.trechos if t.texto.strip()]
        temas = {t.tema for t in com_texto}
        return temas.pop() if com_texto and len(temas) == 1 and None not in temas else None


@dataclass
class Modelo:
    tipo: str          # "aviso_dispensa" | "edital_pregao" | "outro"
    titulo: str
    versao: str        # ex.: "MAR/2026" (rodapé do modelo)
    blocos: list[Bloco]
    orientacoes: list[str] = field(default_factory=list)   # comentários gerais ("leitura obrigatória")

    def bloco(self, id_: str) -> Bloco:
        return next(b for b in self.blocos if b.id == id_)


# ---------------------------------------------------------------------------
# Estilos → nível de numeração
# ---------------------------------------------------------------------------

def _mapa_estilos(styles_xml: bytes) -> dict[str, tuple[str, str]]:
    """styleId → (nome, basedOn)."""
    raiz = ET.fromstring(styles_xml)
    mapa = {}
    for s in raiz.iter(W + "style"):
        nome = s.find(W + "name")
        base = s.find(W + "basedOn")
        mapa[s.get(W + "styleId")] = (nome.get(W + "val") if nome is not None else "",
                                     base.get(W + "val") if base is not None else "")
    return mapa


def _nivel_do_estilo(estilo: str, estilos: dict[str, tuple[str, str]]) -> tuple[int | None, bool]:
    """Sobe a cadeia basedOn até achar "Nivel 01".."Nivel 5". Retorna (nível, opcional)."""
    opcional = False
    atual, vistos = estilo, set()
    while atual and atual not in vistos:
        vistos.add(atual)
        nome = estilos.get(atual, ("", ""))[0]
        # "Nível 2-Opcional", "Nível 3-R", "Nível 2 -Red": redação opcional da AGU (decide-se manter ou não)
        if "opcional" in nome.lower() or re.search(r"-\s*r(ed)?\s*$", nome.strip(), re.IGNORECASE):
            opcional = True
        m = re.fullmatch(r"N[ií]vel\s*0?(\d)", nome.strip(), re.IGNORECASE)
        if m:
            return int(m.group(1)), opcional
        atual = estilos.get(atual, ("", ""))[1]
    return None, opcional


# ---------------------------------------------------------------------------
# Parágrafos e trechos
# ---------------------------------------------------------------------------

def _runs(elemento):
    """Runs de um parágrafo na ordem, inclusive dentro de hyperlink/smartTag; ignora texto excluído."""
    for filho in elemento:
        tag = filho.tag
        if tag == W + "r":
            yield filho
        elif tag in (W + "del", W + "moveFrom"):
            continue
        elif tag in (W + "hyperlink", W + "ins", W + "smartTag", W + "moveTo", W + "fldSimple") or tag == W + "sdt":
            alvo = filho.find(W + "sdtContent") if tag == W + "sdt" else filho
            if alvo is not None:
                yield from _runs(alvo)


def _ligado(rpr, nome: str) -> bool:
    el = rpr.find(W + nome) if rpr is not None else None
    return el is not None and el.get(W + "val", "true") not in ("0", "false", "none")


def _trechos(p) -> list[Trecho]:
    trechos: list[Trecho] = []
    for r in _runs(p):
        partes = []
        for el in r:
            if el.tag == W + "t":
                partes.append(el.text or "")
            elif el.tag == W + "tab":
                partes.append("\t")
            elif el.tag in (W + "br", W + "cr"):
                partes.append("\n")
        texto = "".join(partes)
        if not texto:
            continue
        rpr = r.find(W + "rPr")
        cor = rpr.find(W + "color") if rpr is not None else None
        realce = rpr.find(W + "highlight") if rpr is not None else None
        valor_realce = realce.get(W + "val") if realce is not None else None
        novo = Trecho(
            texto=texto,
            variavel=cor is not None and (cor.get(W + "val") or "").upper() in _VERMELHOS,
            tema=TEMAS.get(valor_realce),
            negrito=_ligado(rpr, "b"),
            italico=_ligado(rpr, "i"),
            sublinhado=_ligado(rpr, "u"),
        )
        anterior = trechos[-1] if trechos else None
        if anterior and (anterior.variavel, anterior.tema, anterior.negrito, anterior.italico, anterior.sublinhado) == \
                (novo.variavel, novo.tema, novo.negrito, novo.italico, novo.sublinhado):
            anterior.texto += texto     # junta runs com a mesma formatação
        else:
            trechos.append(novo)
    return trechos


_PONTE = re.compile(r"[\s.\-/()\[\]]{1,3}")   # separador preto entre pedaços de um mesmo campo


def _opcoes(texto: str) -> list[str]:
    """"[menor preço] OU [maior desconto]" / "[SIM] / [NÃO]" → lista de opções; campo livre → []."""
    if "[" not in texto:
        # "ÓRGÃO OU ENTIDADE PÚBLICA" (tudo em maiúsculas) é um campo só; "Termo de Contrato OU aceitar
        # instrumento equivalente" é escolha entre duas redações
        if texto.strip().isupper() or not re.search(r"\S\s+OU\s+\S", texto):
            return []
        partes = re.split(r"\s+OU\s+", texto.strip())
        return [p.strip() for p in partes if p.strip()] if len(partes) >= 2 else []
    partes = re.split(r"\s+OU\s+|\s+/\s+", texto.strip())
    if len(partes) < 2:
        return []
    return [re.sub(r"^\[|\]$", "", p.strip()).strip() for p in partes if p.strip()]


def _marcar_campos(bloco_id: str, trechos: list[Trecho], titulo: bool = False) -> list[Trecho]:
    """Agrupa os pedaços vermelhos consecutivos em campos. Pedaços pretos curtos entre eles
    (".", "/", "-", "(", " ") fazem parte do mesmo campo: "xxxxx.xxxxxx/xxxx-xx" é um campo só,
    e "XX (valor por extenso)" também (o ")" final é separado do resto do trecho preto)."""
    com_texto = [t for t in trechos if t.texto.strip()]
    if com_texto and all(t.variavel for t in com_texto) and (len("".join(t.texto for t in trechos).strip()) >= 60 or titulo) \
            and "[" not in "".join(t.texto for t in trechos):
        return trechos      # cláusula (ou seção) inteira em vermelho: decide-se manter ou remover, não é campo
    # separa o ")" que fecha um campo do resto do trecho preto seguinte
    saida: list[Trecho] = []
    for t in trechos:
        anterior = saida[-1] if saida else None
        if (anterior is not None and not t.variavel and t.texto.startswith(")") and len(t.texto) > 1
                and anterior.variavel):
            fecha = Trecho(")", False, t.tema, t.negrito, t.italico, t.sublinhado)
            resto = Trecho(t.texto[1:], False, t.tema, t.negrito, t.italico, t.sublinhado)
            saida.extend([fecha, resto])
        else:
            saida.append(t)
    # "o prazo de XX (⟦valor por extenso⟧) dias": a AGU deixa o "XX (" em preto; ele entra no campo,
    # senão o preenchimento vira "XX (5 (cinco))"
    for k in range(1, len(saida)):
        if not (saida[k].variavel and "extenso" in saida[k].texto.lower()):
            continue
        # junta até 3 pedaços pretos anteriores ("XX" e " (" às vezes vêm com formatação diferente)
        inicio = k
        while inicio > 0 and k - inicio < 3 and not saida[inicio - 1].variavel:
            inicio -= 1
            juntos = "".join(t.texto for t in saida[inicio:k])
            m = re.search(r"\b[Xx]{2,}\s*\(\s*$", juntos)
            if m:
                pos = m.start()
                novos = []
                for t in saida[inicio:k]:
                    if pos >= len(t.texto):                     # pedaço todo antes do marcador
                        novos.append(t); pos -= len(t.texto)
                        continue
                    if pos > 0:
                        novos.append(Trecho(t.texto[:pos], False, t.tema, t.negrito, t.italico, t.sublinhado))
                    novos.append(Trecho(t.texto[pos:], True, t.tema, t.negrito, t.italico, t.sublinhado))
                    pos = 0
                saida[inicio:k] = novos
                break
    saida = [t for t in saida if t.texto]
    n, i = 0, 0
    while i < len(saida):
        if not (saida[i].variavel and saida[i].texto.strip()):
            i += 1
            continue
        j = i
        while True:
            k = j + 1
            if k < len(saida) and saida[k].variavel:
                j = k
                continue
            if (k + 1 < len(saida) and not saida[k].variavel and _PONTE.fullmatch(saida[k].texto)
                    and saida[k + 1].variavel):
                j = k + 1
                continue
            break
        grupo = saida[i:j + 1]
        texto = "".join(t.texto for t in grupo)
        if re.fullmatch(r"[\s.,;:]*", texto):
            # pontuação solta em vermelho ("sociedades cooperativas." no fim de lista) não é campo
            for t in grupo:
                t.variavel = False
            i = j + 1
            continue
        if j + 1 < len(saida) and saida[j + 1].texto == ")" and texto.count("(") > texto.count(")"):
            grupo.append(saida[j + 1]); j += 1
        n += 1
        for t in grupo:
            t.campo = f"{bloco_id}.{n}"
        i = j + 1
    return saida


def _comentarios(z: zipfile.ZipFile) -> dict[str, str]:
    if "word/comments.xml" not in z.namelist():
        return {}
    raiz = ET.fromstring(z.read("word/comments.xml"))
    out = {}
    for c in raiz.iter(W + "comment"):
        paragrafos = ["".join(t.text or "" for t in p.iter(W + "t")) for p in c.iter(W + "p")]
        out[c.get(W + "id")] = "\n".join(x for x in paragrafos if x.strip()).strip()
    return out


def _ids_comentarios(elemento) -> list[str]:
    ids = []
    for el in elemento.iter():
        if el.tag in (W + "commentRangeStart", W + "commentReference"):
            i = el.get(W + "id")
            if i not in ids:
                ids.append(i)
    return ids


def _alinhamento(ppr) -> str:
    jc = ppr.find(W + "jc") if ppr is not None else None
    return jc.get(W + "val") if jc is not None else ""


def _versao(z: zipfile.ZipFile) -> str:
    for nome in sorted(n for n in z.namelist() if re.fullmatch(r"word/footer\d+\.xml", n)):
        texto = " ".join(t.text or "" for t in ET.fromstring(z.read(nome)).iter(W + "t"))
        texto = re.sub(r"\s+", "", texto.upper())
        m = re.search(r"(?:VERS[AÃ]O|ATUALIZA[CÇ][AÃ]O):?([A-Z]{3}/\d{4})", texto)
        if m:
            return m.group(1)
    return ""


def _tipo_modelo(titulo: str, textos: str) -> str:
    t = (titulo + " " + textos[:3000]).upper()
    if "CONTRATAÇÃO DIRETA" in t or "DISPENSA ELETRÔNICA" in t:
        return "aviso_dispensa"
    if "EDITAL" in t and "PREGÃO" in t:
        return "edital_pregao"
    return "outro"


# ---------------------------------------------------------------------------
# Leitura do documento
# ---------------------------------------------------------------------------

def ler_modelo(caminho_ou_bytes) -> Modelo:
    """Lê um modelo .docx da AGU. Aceita caminho ou bytes."""
    import io
    fonte = io.BytesIO(caminho_ou_bytes) if isinstance(caminho_ou_bytes, (bytes, bytearray)) else caminho_ou_bytes
    with zipfile.ZipFile(fonte) as z:
        estilos = _mapa_estilos(z.read("word/styles.xml")) if "word/styles.xml" in z.namelist() else {}
        comentarios = _comentarios(z)
        corpo = ET.fromstring(z.read("word/document.xml")).find(W + "body")
        versao = _versao(z)

    blocos: list[Bloco] = []
    usados: set[str] = set()

    def novo_id() -> str:
        return f"B{len(blocos) + 1:03d}"

    def tratar_paragrafo(p, dentro_sumario: bool) -> None:
        ppr = p.find(W + "pPr")
        est = ppr.find(W + "pStyle") if ppr is not None else None
        estilo = est.get(W + "val") if est is not None else ""
        nome_estilo = estilos.get(estilo, ("", ""))[0].lower()
        trechos = _trechos(p)
        notas_ids = [i for i in _ids_comentarios(p) if i not in usados]
        if not "".join(t.texto for t in trechos).strip():
            # Parágrafo vazio que só ancora um comentário: a nota vai para o bloco anterior
            if notas_ids and blocos:
                blocos[-1].notas.extend(comentarios.get(i, "") for i in notas_ids)
                usados.update(notas_ids)
            return
        nivel, opcional = _nivel_do_estilo(estilo, estilos)
        num = ppr.find(f"{W}numPr/{W}numId") if ppr is not None else None
        if num is not None and num.get(W + "val") == "0":
            nivel = None                 # numeração desligada no próprio parágrafo (ex.: preâmbulo)
        if nivel and nivel > 1 and not any(x.tipo == "titulo" for x in blocos):
            nivel = None                 # item antes do primeiro título não é numerado
        if dentro_sumario or nome_estilo.startswith("toc") or "sumário" in nome_estilo or "cabeçalho do sumário" in nome_estilo:
            tipo = "sumario"
        elif nome_estilo == "ou" or estilo == "ou" or "".join(t.texto for t in trechos).strip().upper() == "OU":
            # separador de alternativas: no edital às vezes vem como parágrafo comum em vermelho
            tipo = "ou"
        elif nivel == 1:
            tipo = "titulo"
        elif nivel:
            tipo = "item"
        else:
            tipo = "paragrafo"
        bid = novo_id()
        bloco = Bloco(id=bid, tipo=tipo, nivel=nivel if tipo in ("titulo", "item") else None,
                      estilo=estilo, opcional=opcional, alinhamento=_alinhamento(ppr),
                      trechos=_marcar_campos(bid, trechos, tipo == "titulo") if tipo not in ("sumario", "ou") else trechos,
                      notas=[comentarios.get(i, "") for i in notas_ids])
        usados.update(notas_ids)
        blocos.append(bloco)

    def tratar_tabela(tbl) -> None:
        linhas = []
        for tr in tbl.iter(W + "tr"):
            linha = []
            for tc in tr.findall(W + "tc"):
                linha.append(" ".join("".join(t.texto for t in _trechos(p)).strip() for p in tc.iter(W + "p")).strip())
            linhas.append(linha)
        notas_ids = [i for i in _ids_comentarios(tbl) if i not in usados]
        usados.update(notas_ids)
        blocos.append(Bloco(id=novo_id(), tipo="tabela", linhas=linhas,
                            notas=[comentarios.get(i, "") for i in notas_ids]))

    def percorrer(elemento, dentro_sumario=False) -> None:
        for filho in elemento:
            if filho.tag == W + "p":
                tratar_paragrafo(filho, dentro_sumario)
            elif filho.tag == W + "tbl":
                tratar_tabela(filho)
            elif filho.tag == W + "sdt":
                conteudo = filho.find(W + "sdtContent")
                galeria = filho.find(f"{W}sdtPr/{W}docPartObj/{W}docPartGallery")
                eh_sumario = galeria is not None and "contents" in (galeria.get(W + "val") or "").lower()
                if conteudo is not None:
                    percorrer(conteudo, dentro_sumario or eh_sumario)

    percorrer(corpo)

    # A primeira nota costuma ser "Orientações para uso do modelo – leitura obrigatória": é geral, não do bloco.
    orientacoes = []
    for b in blocos:
        gerais = [n for n in b.notas if re.match(r"\s*(orienta[çc][õo]es|notas explicativas)\b.*leitura obrigat", n, re.I | re.S)]
        if gerais:
            orientacoes.extend(gerais)
            b.notas = [n for n in b.notas if n not in gerais]

    titulo = next((b.texto.strip() for b in blocos if b.tipo == "paragrafo" and b.texto.strip()), "")
    return Modelo(tipo=_tipo_modelo(titulo, " ".join(b.texto for b in blocos[:60])),
                  titulo=titulo, versao=versao, blocos=blocos, orientacoes=orientacoes)


def numerar(blocos: list[Bloco]) -> dict[str, str]:
    """Numeração automática (1., 1.1., 1.1.1.) só dos blocos que ficaram — renumera após exclusões."""
    contadores = [0] * 6
    numeros = {}
    for b in blocos:
        if b.tipo not in ("titulo", "item") or not b.nivel:
            continue
        n = min(b.nivel, 5)
        contadores[n] += 1
        for k in range(n + 1, 6):
            contadores[k] = 0
        for k in range(1, n):          # nível pulado (ex.: item 3 sem item 2 antes) começa em 1
            contadores[k] = contadores[k] or 1
        numeros[b.id] = ".".join(str(contadores[k]) for k in range(1, n + 1)) + "."
    return numeros
