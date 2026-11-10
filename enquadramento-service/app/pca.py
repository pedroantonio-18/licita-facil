"""
Plano de Contratações Anual (PCA) da SJGO: leitura do PDF publicado no portal e busca das
demandas semelhantes ao objeto dos autos (análise de fracionamento, art. 4º da IN 67/2021).

O PCA é um PDF do SEI com uma tabela de 8 colunas (unidade, ID, descrição, forma de
contratação, nova/prorrogação, valor total, desembolso no ano, processo). Quando a tabela vem
como texto (PCA 2026), é lida aqui, sem IA. Quando vem como imagem (PCA 2027), a lista pode
ser importada de um JSON — digitado ou obtido pelo servidor com a IA que ele usa.

A busca só SUGERE demandas parecidas: quem decide quais entram na soma é o servidor (o PCA
não traz PDM/CATMAT, então a semelhança é pela descrição).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

PASTA = Path(os.environ.get("ENQUADRAMENTO_DADOS", Path(__file__).resolve().parent.parent / "data"))
_ID = re.compile(r"[A-Z]{2,6}_[A-Z0-9/-]{2,12}_\d{3,4}_\d{4}")
_VAZIAS = {"de", "da", "do", "das", "dos", "para", "com", "em", "na", "no", "nas", "nos", "por", "e", "a", "o", "as", "os",
           "contratacao", "aquisicao", "prestacao", "servico", "servicos", "empresa", "especializada", "fornecimento",
           "secao", "judiciaria", "goias", "justica", "federal", "subsecoes", "subsecao", "sjgo", "goiania", "sede",
           "nova", "prorrogacao", "contrato", "exercicio", "conforme", "visando", "atender", "destinados", "destinado"}


@dataclass
class DemandaPCA:
    id: str
    unidade: str
    descricao: str
    forma: str           # "Contratação direta - Dispensa", "Licitação - Pregão (…)", "-"
    tipo: str            # "Nova contratação", "Prorrogação (Contrato ou ARP)"…
    valor_total: str     # "7.070,16"
    desembolso: str      # desembolso estimado no ano do PCA
    processo: str


def _limpo(c) -> str:
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def _valor(c: str) -> str:
    m = re.search(r"\d[\d.]*,\d{2}", c or "")
    return m.group(0) if m else ""


def ler_pdf(conteudo: bytes) -> list[DemandaPCA]:
    """Demandas da tabela do PCA (PDF com texto). Lista vazia se a tabela estiver em imagem."""
    import fitz
    demandas: list[DemandaPCA] = []
    with fitz.open(stream=conteudo, filetype="pdf") as doc:
        for pagina in doc:
            for tabela in pagina.find_tables().tables:
                if tabela.col_count != 8:
                    continue
                for linha in tabela.extract():
                    c = [_limpo(x) for x in linha]
                    codigo = c[1].replace(" ", "")
                    if _ID.fullmatch(codigo):
                        demandas.append(DemandaPCA(codigo, c[0].replace("/ ", "/"), c[2], c[3], c[4], _valor(c[5]),
                                                   _valor(c[6]), c[7].replace(" ", "")))
                    elif not c[1] and c[2] and demandas and "descri" not in c[2].lower():
                        demandas[-1].descricao += " " + c[2]          # descrição que continua na página seguinte
    return demandas


def de_json(dados) -> list[DemandaPCA]:
    """Demandas a partir de JSON (lista colada pelo servidor, ex.: PCA cuja tabela está em imagem)."""
    if isinstance(dados, dict):
        dados = dados.get("demandas", [])
    saida = []
    for n, d in enumerate(dados if isinstance(dados, list) else [], 1):
        if not isinstance(d, dict) or not str(d.get("descricao", "")).strip():
            continue
        saida.append(DemandaPCA(
            id=_limpo(str(d.get("id", ""))) or f"linha {n}", unidade=_limpo(str(d.get("unidade", ""))),
            descricao=_limpo(str(d["descricao"])), forma=_limpo(str(d.get("forma", ""))), tipo=_limpo(str(d.get("tipo", ""))),
            valor_total=_valor(str(d.get("valor_total", ""))), desembolso=_valor(str(d.get("desembolso", ""))),
            processo=_limpo(str(d.get("processo", "")))))
    return saida


PEDIDO_IA = """O Plano de Contratações Anual (PCA) da Seção Judiciária de Goiás está ANEXADO a esta conversa (PDF).
A tabela de demandas pode estar em imagem: leia todas as páginas. Transcreva TODAS as linhas da tabela, sem
resumir e sem inventar. Responda apenas com JSON neste formato:
{"demandas": [{"id": "SJGO_SETMAT_0005_2027", "unidade": "NUASG/SETMAT", "descricao": "texto completo do objeto",
  "forma": "Contratação direta - Dispensa", "tipo": "Nova contratação", "valor_total": "18.000,00",
  "desembolso": "18.000,00", "processo": "0000000-00.2026.4.01.8006"}]}
Se o anexo não estiver disponível, responda apenas {"erro": "anexo não recebido"}."""


# ---------------------------------------------------------------------------
# Armazenamento (um arquivo por exercício)
# ---------------------------------------------------------------------------

def _arquivo(ano: str) -> Path:
    if not re.fullmatch(r"20\d{2}", ano):
        raise ValueError("Exercício inválido")
    return PASTA / f"pca_{ano}.json"


def salvar(ano: str, demandas: list[DemandaPCA], origem: str) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    _arquivo(ano).write_text(json.dumps({"origem": origem, "demandas": [asdict(d) for d in demandas]},
                                        ensure_ascii=False, indent=1), encoding="utf-8")


def carregar(ano: str) -> list[DemandaPCA]:
    arq = _arquivo(ano)
    if not arq.is_file():
        return []
    return [DemandaPCA(**d) for d in json.loads(arq.read_text(encoding="utf-8"))["demandas"]]


def anos() -> dict[str, dict]:
    saida = {}
    for arq in sorted(PASTA.glob("pca_20??.json")):
        dados = json.loads(arq.read_text(encoding="utf-8"))
        saida[arq.stem[-4:]] = {"demandas": len(dados["demandas"]), "origem": dados.get("origem", "")}
    return saida


# ---------------------------------------------------------------------------
# Busca de demandas semelhantes
# ---------------------------------------------------------------------------

def _palavras(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(p for p in re.findall(r"[a-z0-9]{3,}", t) if p not in _VAZIAS)


def _reais(valor: str) -> Decimal:
    try:
        return Decimal(valor.replace(".", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _raiz(palavra: str) -> str:
    """Raiz simples para casar plural e gênero: "elétricos"/"elétrica" → "eletr", "materiais" → "mater"."""
    return palavra[:5] if len(palavra) > 5 else palavra.rstrip("s")


def buscar(demandas: list[DemandaPCA], objeto: str, limite: int = 8, corte: int = 50) -> list[dict]:
    """Demandas do PCA mais parecidas com o objeto, da mais para a menos parecida.

    Nota = cobertura: quanto das palavras-chave do objeto aparece na descrição da demanda
    (com pelo menos duas em comum, para uma palavra solta como "serviços" não puxar tudo)."""
    alvo = {_raiz(p): p for p in _palavras(objeto).split()}
    if not alvo:
        return []
    minimo = 1 if len(alvo) == 1 else 2
    achados = []
    for d in demandas:
        raizes = {_raiz(p) for p in _palavras(d.descricao).split()}
        comuns = sorted(alvo[r] for r in alvo if r in raizes)
        nota = round(100 * len(comuns) / len(alvo))
        if len(comuns) >= minimo and nota >= corte:
            achados.append({**asdict(d), "semelhanca": nota, "palavras_comuns": comuns,
                            "dispensa": "dispensa" in d.forma.lower()})
    achados.sort(key=lambda x: (-x["semelhanca"], -_reais(x["desembolso"])))
    return achados[:limite]
