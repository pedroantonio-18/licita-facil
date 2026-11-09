"""
Reconhecimento e leitura de certidões de habilitação.

Cada tipo de certidão é reconhecido pelo texto característico do órgão
emissor e lido com regras próprias (onde fica a validade, o que significa
"negativa" etc.). Os textos de referência são os modelos padrão de cada
órgão; ajuste aqui quando um órgão mudar o layout.

Um PDF pode trazer uma certidão ou várias (o servidor às vezes junta tudo
num arquivo só): a classificação é feita página a página, e páginas sem
título próprio são tratadas como continuação da certidão anterior.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.texto import DATA, cnpjs_no_texto, cpfs_no_texto, normalizar, para_data, primeira_data_apos

# Resultados possíveis
NEGATIVA = "negativa"
POSITIVA_EFEITO_NEGATIVA = "positiva_com_efeito_de_negativa"
POSITIVA = "positiva"
PENDENTE = "pendente"                 # ex.: sistema do órgão indisponível na consulta
INFORMATIVO = "informativo"           # consultas sem resultado "negativa/positiva" (SICAF)
INDETERMINADO = "indeterminado"

ROTULO_RESULTADO = {
    NEGATIVA: "Negativa / nada consta",
    POSITIVA_EFEITO_NEGATIVA: "Positiva com efeito de negativa",
    POSITIVA: "Positiva / consta",
    PENDENTE: "Pendente (sistema indisponível)",
    INFORMATIVO: "Consulta",
    INDETERMINADO: "Não identificado",
}


@dataclass(frozen=True)
class TipoCertidao:
    id: str
    nome: str
    ordem: int                    # posição dentro do bloco no PDF para o SEI
    identificacao: re.Pattern     # aplicado ao texto normalizado da página
    abrangencia: str              # "raiz": vale para matriz e filiais; "estabelecimento": CNPJ exato
    validade: str                 # "impressa" (data no documento) | "consulta" (N dias da emissão) | "nenhuma"
    parametro_dias: str | None = None   # nome do parâmetro de dias, quando validade = "consulta"
    bloco: int = 2                # bloco de juntada no SEI (ver BLOCOS)


# Blocos temáticos em que a SELIT junta os documentos no SEI (um PDF por bloco)
BLOCOS = {
    1: "Habilitação Jurídica",
    2: "Regularidade Fiscal, Social e Trabalhista",
    3: "Idoneidade",
    4: "Qualificação Econômico-Financeira",
}

# Certidões de regularidade que o SICAF espelha: se estiverem válidas nele,
# o bloco 2 é só o relatório do SICAF (resposta da SELIT, 04/11/2026)
REGULARIDADE = ("federal", "fgts", "trabalhista", "estadual", "municipal")

def _perto_de_certidao(termos: str) -> str:
    """O termo do órgão perto da palavra "certidão", antes ou depois (cabeçalhos variam por estado)."""
    return rf"certid.{{0,200}}({termos})|({termos}).{{0,200}}certid"


# A ordem da lista é a ordem de teste: os mais específicos primeiro. A
# consolidada do TCU cita CEIS/CNEP; o SICAF cita Receita e FGTS; contratos
# sociais citam falência e prefeitura em cláusulas — por isso falência,
# estadual e municipal exigem "certidão" no texto e habilitação vem por último.
TIPOS: list[TipoCertidao] = [
    TipoCertidao("tcu", "Consulta Consolidada de Pessoa Jurídica (TCU, CNJ, CEIS, CNEP)", 1,
                 re.compile(r"consulta consolidada de pessoa juridica"), "raiz", "consulta", "dias_consultas", 3),
    TipoCertidao("sicaf", "SICAF — Situação do Fornecedor", 1,
                 re.compile(r"\bsicaf\b|sistema de cadastramento unificado de fornecedores"), "raiz", "nenhuma", None, 2),
    TipoCertidao("federal", "Certidão de Débitos Relativos a Tributos Federais e à Dívida Ativa da União", 2,
                 re.compile(r"tributos federais|divida ativa da uniao"), "raiz", "impressa", None, 2),
    TipoCertidao("fgts", "Certificado de Regularidade do FGTS — CRF", 3,
                 re.compile(r"regularidade do fgts|certificado de regularidade.{0,40}fgts"), "estabelecimento", "impressa", None, 2),
    TipoCertidao("trabalhista", "Certidão de Débitos Trabalhistas — CNDT", 4,
                 re.compile(r"debitos trabalhistas|\bcndt\b"), "raiz", "impressa", None, 2),
    TipoCertidao("cgu", "Certidões da CGU (CEIS/CNEP/correcional)", 2,
                 re.compile(r"certidao (negativa )?correcional|controladoria.geral da uniao|"
                            r"cadastro nacional de empresas (inidoneas|punidas)|portal da transparencia"),
                 "raiz", "consulta", "dias_consultas", 3),
    TipoCertidao("falencia", "Certidão de Falência e Recuperação Judicial", 1,
                 re.compile(r"certid.{0,120}(falencia|recuperacao judicial|concordata)|"
                            r"(falencia|recuperacao judicial|concordata).{0,60}certid|"
                            # TJGO: "CERTIDÃO PARA LICITAÇÃO PÚBLICA ... pesquisando as ações de Falência"
                            r"pesquisando as acoes de\s+falencia"),
                 "raiz", "consulta", "dias_falencia", 4),
    TipoCertidao("estadual", "Certidão de Regularidade Fiscal Estadual", 5,
                 re.compile(_perto_de_certidao(
                     r"tributos estaduais|divida ativa (estadual|do estado)|secretaria (de estado )?da (economia|fazenda)|"
                     r"\bsefaz\b|fazenda (publica )?estadual|procuradoria.geral do estado")),
                 "estabelecimento", "impressa", None, 2),
    TipoCertidao("municipal", "Certidão de Regularidade Fiscal Municipal", 6,
                 re.compile(_perto_de_certidao(
                     r"tributos municipais|prefeitura|fazenda (publica )?municipal|secretaria municipal|"
                     r"divida ativa (do )?municip")),
                 "estabelecimento", "impressa", None, 2),
    TipoCertidao("habilitacao", "Documentos de Habilitação Jurídica", 1,
                 re.compile(r"contrato social|alteracao contratual|consolidacao (do )?contrat|ato constitutivo|"
                            r"estatuto social|requerimento de empresario|condicao de microempreendedor|\bccmei\b|"
                            r"carteira nacional de habilitacao|cedula de identidade|registro geral|"
                            r"documento de identi"),
                 "raiz", "nenhuma", None, 1),
]
TIPOS_POR_ID = {t.id: t for t in TIPOS}
# Documento sem título reconhecível: quase sempre é documento de habilitação
# jurídica digitalizado (RG, CNH, contrato escaneado); vai para o bloco 1 e
# pede conferência.
OUTRO = TipoCertidao("outro", "Documento não identificado", 9, re.compile(r"(?!)"), "raiz", "nenhuma", None, 1)


def classificar_pagina(texto: str) -> TipoCertidao | None:
    """Tipo da página pelo título característico, ou None se for continuação."""
    t = normalizar(texto)[:3000]
    for tipo in TIPOS:
        if tipo.identificacao.search(t):
            return tipo
    return None


@dataclass
class CertidaoLida:
    """Uma certidão encontrada num arquivo, com o que foi possível ler dela."""
    arquivo: str
    paginas: list[int]                       # 1-based
    tipo: str
    tipo_nome: str
    cnpjs: list[str] = field(default_factory=list)
    emissao: date | None = None
    validade_inicio: date | None = None
    validade_fim: date | None = None
    validade_origem: str = ""                # "impressa", "N dias da emissão", ""
    resultado: str = INDETERMINADO
    detalhes: list[str] = field(default_factory=list)   # ex.: resultado de cada cadastro do TCU
    texto_lido: bool = True                  # False para páginas digitalizadas sem texto
    cpfs: list[str] = field(default_factory=list)        # certidões de pessoa física (sócios, na CGU)
    # Só no SICAF: validade de cada certidão espelhada (None = SICAF não informa)
    sicaf_validades: dict[str, date | None] = field(default_factory=dict)
    impedimentos: list[str] = field(default_factory=list)  # ocorrências/impedimentos ≠ "nada consta"


def _resultado_generico(t: str) -> str:
    if re.search(r"positiva com efeitos? de negativa", t):
        return POSITIVA_EFEITO_NEGATIVA
    positiva = re.search(
        r"certidao positiva|constam? (debitos|pendencias|registros)|\bconstam? como inadimplente|"
        r"(?<!nada )(?<!nao )\bconstam? (o |os |a |as )?(registro|pedido|distribuic|acao|acoes|processo|feito)", t)
    negada = re.search(r"nao constam? (debitos|pendencias|registros)|nao consta como inadimplente", t)
    if positiva and not negada:
        return POSITIVA
    if re.search(r"certidao negativa|certidao de regularidade|nada consta|nao consta|nao constam|"
                 r"situacao regular|regular perante|nao ha (debitos|registros|pendencias)", t):
        return NEGATIVA
    return INDETERMINADO


def _ler_tcu(t: str, c: CertidaoLida, original: str) -> None:
    m = re.search(DATA + r"\s+\d{1,2}:\d{2}(?::\d{2})?\s*consulta realizada em", t) or \
        re.search(r"consulta realizada em:?\s*" + DATA, t)
    c.emissao = para_data(m.group(1)) if m else None
    # Lido do texto original (com acentos) para o relatório; decidido no normalizado
    texto = " ".join(original.split())
    cadastros = re.findall(
        r"Cadastro:\s*(.+?)\s*Resultado da consulta:\s*(.+?)(?:\s*Para acessar|\s*Órgão Gestor|\s*Obs:|$)",
        texto, re.IGNORECASE)
    resultados = []
    for cadastro, resultado in cadastros:
        nome = cadastro.split(" - ")[0].strip()
        c.detalhes.append(f"{nome}: {resultado.strip()}")
        resultados.append(normalizar(resultado))
    # "Sistema do CNJ está indisponível" / "Dados do sistema CNJ estão indisponíveis" /
    # "Erro na consulta": o cadastro não respondeu — nunca vira "consta" nem "nada consta"
    if any(re.search(r"indisponive|erro|falha|nao (foi )?possivel|tente novamente", r) for r in resultados):
        c.resultado = PENDENTE
    elif resultados and all("nada consta" in r for r in resultados):
        c.resultado = NEGATIVA
    elif resultados:
        c.resultado = POSITIVA
    else:
        c.resultado = INDETERMINADO


# Rótulos das certidões na declaração "Situação do Fornecedor" do SICAF.
# A data de validade vem logo depois do rótulo, às vezes precedida de "Validade:".
_SICAF_ROTULOS = {
    "federal": r"receita federal e pgfn",
    "fgts": r"\bfgts\b",
    "trabalhista": r"\btrabalhista\b",
    "estadual": r"receita estadual(?:/distrital)?",
    "municipal": r"receita municipal",
}


def _ler_sicaf(t: str, c: CertidaoLida) -> None:
    # "Emitido em: 27/10/2026 15:55" (declaração) ou "Brasília, 19 de Maio de 2026" (consultas por nível).
    # Nunca a maior data do documento: ela costuma ser o vencimento do cadastro.
    c.emissao = primeira_data_apos(t, r"emitido em:?") or primeira_data_apos(t, r"brasilia,?")

    m = re.search(r"situacao do fornecedor:?\s*(\w+)", t)
    if m:
        c.detalhes.append(f"Situação do fornecedor: {m.group(1).capitalize()}")
    if "possui pendencia" in t or re.search(r"\birregular\b", t):
        c.detalhes.append("SICAF indica pendência — conferir o documento")

    # Validade de cada certidão espelhada, só na parte dos níveis cadastrados
    inicio = re.search(r"niveis cadastrados|regularidade fiscal", t)
    trecho = t[inicio.start():] if inicio else t
    for tipo, rotulo in _SICAF_ROTULOS.items():
        m = re.search(rotulo + r"(?:\s*\(?[a-z/ ]{0,20}\)?)?\s*(?:validade:?\s*)?" + DATA, trecho)
        c.sicaf_validades[tipo] = para_data(m.group(1)) if m else None
    if any(c.sicaf_validades.values()):
        nomes = {"federal": "Receita/PGFN", "fgts": "FGTS", "trabalhista": "Trabalhista",
                 "estadual": "Estadual", "municipal": "Municipal"}
        lidas = ", ".join(f"{nomes[k]} {v:%d/%m/%Y}" for k, v in c.sicaf_validades.items() if v)
        c.detalhes.append(f"Validades no SICAF — {lidas}")

    # "Ocorrência: Nada Consta", "Impedimento de Licitar: Nada Consta"... (exige o ":" para não
    # confundir com o título da seção "Ocorrências e Impedimentos")
    for rotulo, nome in ((r"ocorrencia", "Ocorrência"), (r"impedimento de licitar", "Impedimento de licitar"),
                         (r"vinculo com .?servico publico.?", "Vínculo com serviço público"),
                         (r"ocorrencias impeditivas indiretas", "Ocorrências impeditivas indiretas")):
        m = re.search(r"\b" + rotulo + r":\s*(.{0,40})", t)
        if m and not m.group(1).startswith("nada consta"):
            c.impedimentos.append(f"{nome}: {m.group(1).split(':')[0].strip()}")
    c.resultado = INFORMATIVO


def _ler_validade_impressa(t: str, c: CertidaoLida) -> None:
    # Intervalo "Validade: 01/10/2026 a 30/10/2026" (CRF/FGTS)
    m = re.search(r"validade:?\s*" + DATA + r"\s*(?:a|ate)\s*" + DATA, t)
    if m:
        c.validade_inicio, c.validade_fim = para_data(m.group(1)), para_data(m.group(2))
    else:
        c.validade_fim = (
            primeira_data_apos(t, r"valid[ao] ate")
            or primeira_data_apos(t, r"validade:?")
            or primeira_data_apos(t, r"data de validade")
        )
    if c.validade_fim:
        c.validade_origem = "impressa"
        return
    # "válida por 180 (cento e oitenta) dias" a partir da emissão
    m = re.search(r"valid[ao] (?:por|pelo prazo de)\s*(\d{1,3})\s*(?:\([^)]*\)\s*)?dias|(\d{1,3})\s*(?:\([^)]*\)\s*)?dias,? contados", t)
    if m and c.emissao:
        dias = int(m.group(1) or m.group(2))
        c.validade_fim = c.emissao + timedelta(days=dias)
        c.validade_origem = f"{dias} dias da emissão (impresso)"


def _ler_emissao(t: str) -> date | None:
    for rotulo in (r"emitida as \d{1,2}:\d{2}(?::\d{2})? do dia", r"expedicao:?", r"emitid[ao] em:?",
                   r"data (?:e hora )?da (?:emissao|expedicao|consulta):?", r"emissao:?", r"gerad[ao] em:?",
                   r"certidao emitida em:?", r"consulta realizada em:?", r"informacao obtida em:?",
                   r"publicado digitalmente em"):
        d = primeira_data_apos(t, rotulo)
        if d:
            return d
    # Fecho: "Goiânia, 05 de outubro de 2026" ou "GOIANIA(GO), 4 DE NOVEMBRO DE 2026" (a última que aparecer)
    datas = re.findall(r"[a-z)]+,\s*(\d{1,2}\s+(?:de\s+)?[a-z]+\s+de\s+\d{4})", t)
    return para_data(datas[-1]) if datas else None


def ler_certidao(texto: str, tipo: TipoCertidao, arquivo: str, paginas: list[int]) -> CertidaoLida:
    """Extrai CNPJ, emissão, validade e resultado de uma certidão já classificada."""
    t = normalizar(texto)
    c = CertidaoLida(arquivo=arquivo, paginas=paginas, tipo=tipo.id, tipo_nome=tipo.nome,
                     cnpjs=cnpjs_no_texto(texto), cpfs=cpfs_no_texto(texto), texto_lido=bool(t.strip()))
    if tipo.id == "tcu":
        _ler_tcu(t, c, texto)
    elif tipo.id == "sicaf":
        _ler_sicaf(t, c)
    elif tipo.validade == "nenhuma":
        c.resultado = INFORMATIVO      # documento de habilitação jurídica: não tem validade nem resultado
    else:
        c.emissao = _ler_emissao(t)
        c.resultado = _resultado_generico(t)
        if tipo.validade == "impressa":
            _ler_validade_impressa(t, c)
    return c


def ler_pdf(paginas_texto: list[str], arquivo: str) -> list[CertidaoLida]:
    """
    Separa as certidões de um PDF e lê cada uma.

    Página sem título reconhecível continua a certidão anterior; se o
    arquivo começar sem título reconhecível, vira "documento não identificado".
    """
    grupos: list[tuple[TipoCertidao, list[int]]] = []
    for i, texto in enumerate(paginas_texto, 1):
        tipo = classificar_pagina(texto)
        if tipo and (not grupos or grupos[-1][0].id != tipo.id or _nova_certidao(texto)):
            grupos.append((tipo, [i]))
        elif grupos:
            grupos[-1][1].append(i)
        else:
            grupos.append((OUTRO, [i]))

    certidoes = []
    for tipo, paginas in grupos:
        texto = "\n".join(paginas_texto[p - 1] for p in paginas)
        certidoes.append(ler_certidao(texto, tipo, arquivo, paginas))
    return certidoes


def _nova_certidao(texto: str) -> bool:
    """Página com cabeçalho de certidão (e não só continuação do mesmo tipo)."""
    return bool(re.search(r"^\W*(certidao|certificado|consulta consolidada)", normalizar(texto)[:200]))
