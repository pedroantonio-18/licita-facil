"""
Questionário do caso: perguntas objetivas que decidem grupos de cláusulas do modelo da AGU
sem IA nenhuma.

Cada resposta vira decisões (remover, manter, escolher opção, manter ou retirar trecho) sobre
blocos encontrados pelo TEXTO da cláusula, e não pelo número — assim a regra continua valendo
quando a AGU renumera o modelo numa versão nova. Remover um item leva os subitens junto
(regra da montagem). Decisões do servidor e da IA prevalecem sobre as do questionário.

Algumas decisões nem precisam de pergunta: saem do formulário (critério de julgamento, margem
de preferência) ou dos temas marcados (mão de obra exclusiva).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.modelo import Bloco, Modelo
from app.montagem import MANTER_CAMPO, Decisoes


@dataclass
class Pergunta:
    id: str
    texto: str
    opcoes: list[tuple[str, str]]
    tipos: tuple[str, ...] = ("aviso_dispensa", "edital_pregao")
    ajuda: str = ""


PERGUNTAS = [
    Pergunta("instrumento", "A contratação será formalizada por",
             [("contrato", "Termo de Contrato"), ("empenho", "Nota de Empenho (substitui o contrato)")]),
    Pergunta("divisao", "Divisão do objeto",
             [("item_unico", "Item único"), ("itens", "Vários itens"), ("grupo_unico", "Grupo único"),
              ("grupos", "Grupos"), ("itens_grupos", "Itens e grupos")]),
    Pergunta("engenharia", "É obra ou serviço de engenharia?", [("nao", "Não"), ("sim", "Sim")],
             ajuda="Engenharia mantém as regras de exequibilidade (75%/85%), preço unitário e projeto básico."),
    Pergunta("consorcio", "Admite participação de empresas em consórcio?", [("nao", "Não"), ("sim", "Sim")]),
    Pergunta("cooperativas", "Admite sociedades cooperativas?", [("sim", "Sim"), ("nao", "Não")]),
    Pergunta("pessoa_fisica", "Admite pessoa física?", [("nao", "Não"), ("sim", "Sim")]),
    Pergunta("planilha", "Exige planilha de custos e formação de preços?", [("nao", "Não"), ("sim", "Sim")]),
    Pergunta("me_epp_itens", "Participação exclusiva de ME/EPP",
             [("todos", "Em todos os itens"), ("alguns", "Só em alguns itens"), ("nenhum", "Em nenhum item")],
             ajuda="Regra da LC 123/2006: item de até R$ 80.000,00 é exclusivo."),
    Pergunta("objeto_bens", "O objeto é", [("bens", "Compra de bens"), ("servicos", "Serviço")], ("edital_pregao",),
             ajuda="Na compra de bens a proposta informa marca e fabricante."),
    Pergunta("orcamento_sigiloso", "O orçamento estimado será sigiloso?", [("nao", "Não"), ("sim", "Sim")], ("edital_pregao",)),
    Pergunta("vistoria", "Haverá vistoria prévia ao local?", [("nao", "Não"), ("sim", "Sim")], ("edital_pregao",)),
]


def perguntas_para(tipo: str) -> list[dict]:
    return [{"id": p.id, "texto": p.texto, "opcoes": p.opcoes, "ajuda": p.ajuda} for p in PERGUNTAS if tipo in p.tipos]


def _n(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


@dataclass
class _Aplicador:
    modelo: Modelo
    d: Decisoes = field(default_factory=Decisoes)

    def blocos(self, *inicios: str, contem: str = "") -> list[Bloco]:
        alvos = [_n(i) for i in inicios]
        achados = []
        for b in self.modelo.blocos:
            if b.tipo == "sumario":
                continue
            t = _n(b.texto)
            if any(t.startswith(a) for a in alvos) and (not contem or _n(contem) in t):
                achados.append(b)
        return achados

    def remover(self, motivo: str, *inicios: str, contem: str = "") -> None:
        for b in self.blocos(*inicios, contem=contem):
            self.d.remover.setdefault(b.id, motivo)
            self.d.origem.setdefault(b.id, "questionario")

    def manter(self, motivo: str, *inicios: str, contem: str = "") -> None:
        for b in self.blocos(*inicios, contem=contem):
            if b.id not in self.d.remover:
                self.d.manter.add(b.id)
                self.d.origem.setdefault(b.id, "questionario")
                self.d.motivos.setdefault(b.id, motivo)

    def escolher(self, motivo: str, opcao: str, *inicios: str) -> None:
        """Escolhe, no campo de opções do bloco, a opção que começa com `opcao`."""
        for b in self.blocos(*inicios):
            for c in b.campos:
                escolhida = next((o for o in c.opcoes if _n(o).startswith(_n(opcao))), None)
                if escolhida:
                    self.d.campos.setdefault(c.id, escolhida)
                    self.d.origem.setdefault(c.id, "questionario")
                    self.d.motivos.setdefault(c.id, motivo)

    def trecho(self, motivo: str, manter: bool, *inicios: str, texto_trecho: str) -> None:
        """Mantém ou retira o trecho opcional (campo vermelho sem lacuna) que contém `texto_trecho`."""
        for b in self.blocos(*inicios):
            for c in b.campos:
                if _n(texto_trecho) in _n(c.texto) and not c.opcoes:
                    self.d.campos.setdefault(c.id, MANTER_CAMPO if manter else "")
                    self.d.origem.setdefault(c.id, "questionario")
                    self.d.motivos.setdefault(c.id, motivo)

    def manter_campos_padrao(self, motivo: str, *inicios: str) -> None:
        """Campos vermelhos que são só referência legal padrão ("Lei nº 14.133, de 2021")."""
        for b in self.blocos(*inicios):
            for c in b.campos:
                if not c.opcoes and re.search(r"lei n|arts?\. \d", _n(c.texto)):
                    self.d.campos.setdefault(c.id, MANTER_CAMPO)
                    self.d.origem.setdefault(c.id, "questionario")
                    self.d.motivos.setdefault(c.id, motivo)


def aplicar(modelo: Modelo, respostas: dict, dados: dict | None = None, temas: set[str] | None = None) -> Decisoes:
    """Decisões do questionário (origem "questionario") e das regras que saem do formulário."""
    a = _Aplicador(modelo)
    dados = dados or {}
    temas = temas or set()
    r = {k: v for k, v in (respostas or {}).items() if v}
    q = lambda pid, valor: f"Questionário: {next(p.texto for p in PERGUNTAS if p.id == pid)} — {valor}"

    # --- Sem pergunta: saem do formulário, dos temas ou são só marcadores do modelo ---
    criterio = _n(dados.get("criterio", ""))
    if criterio.startswith("menor preco"):
        a.escolher("Critério de menor preço (formulário)", "valor unitário", "o lance devera ser ofertado pelo")
    elif criterio.startswith("maior desconto"):
        a.escolher("Critério de maior desconto (formulário)", "percentual de desconto", "o lance devera ser ofertado pelo")
    if _n(dados.get("margem_preferencia", "NÃO")).startswith("nao"):
        a.remover("Sem margem de preferência (formulário)", "caso o fornecedor nao venha a comprovar o atendimento dos requisitos para fazer jus ao beneficio da margem")
    if "mao_de_obra_exclusiva" not in temas:
        a.manter("Sem mão de obra exclusiva: ME/EPP podem optar pelo Simples", "na presente licitacao, a microempresa e a empresa de pequeno porte poderao se beneficiar")
        a.remover("Sem mão de obra exclusiva", "na presente licitacao, a microempresa e a empresa de pequeno porte nao poderao se beneficiar",
                  "anexo vii – declaracao de responsabilidade pelo enquadramento sindical")
    a.remover("Marcador genérico de anexo do modelo", "anexo v – (...)", "anexo viii – (...)")
    a.remover("Grande vulto: não se aplica às contratações da SJGO", "nas contratacoes de obras, servicos e fornecimentos de grande vulto")

    # --- Instrumento ---
    inst = r.get("instrumento")
    if inst == "empenho":
        m = q("instrumento", "Nota de Empenho")
        a.escolher(m, "aceitar instrumento equivalente", "o adjudicatario tera o prazo de")
        a.remover(m, "alternativamente a convocacao para comparecer perante o orgao ou entidade para a assinatura do termo de contrato",
                  "anexo iii – minuta de termo de contrato")
        a.manter(m, "o aceite da nota de empenho", "a contratada se vincula a sua proposta", "referida nota esta substituindo o contrato",
                 "a contratada reconhece que as hipoteses de rescisao", "anexo v –regras aplicaveis ao instrumento substitutivo",
                 "anexo v – regras aplicaveis ao instrumento substitutivo")
        a.manter_campos_padrao(m, "referida nota esta substituindo o contrato", "a contratada reconhece que as hipoteses de rescisao")
    elif inst == "contrato":
        m = q("instrumento", "Termo de Contrato")
        a.escolher(m, "termo de contrato", "o adjudicatario tera o prazo de")
        a.remover(m, "o aceite da nota de empenho", "anexo v –regras aplicaveis ao instrumento substitutivo",
                  "anexo v – regras aplicaveis ao instrumento substitutivo")
        a.manter(m, "anexo iii – minuta de termo de contrato")

    # --- Divisão do objeto ---
    div = r.get("divisao")
    if div:
        m = q("divisao", dict(next(p.opcoes for p in PERGUNTAS if p.id == "divisao"))[div])
        alternativas = {
            "itens": "a licitacao sera dividida em itens",
            "item_unico": "a licitacao sera realizada em unico item",
            "grupos": "a licitacao sera dividida em grupos",
            "grupo_unico": "a licitacao sera realizada em grupo unico",
            "itens_grupos": "a licitacao sera dividida em item(s) e grupo(s)",
        }
        for chave, inicio in alternativas.items():
            (a.manter if chave == div else a.remover)(m, inicio)
        if div in ("item_unico", "grupo_unico"):
            a.remover(m, "havendo mais de um item, faculta-se ao fornecedor",
                      "o fornecedor provisoriamente vencedor em um item, que estiver concorrendo em outro item",
                      "nao havendo a comprovacao cumulativa dos requisitos de habilitacao, a inabilitacao recaira sobre o(s) item")

    # --- Engenharia ---
    eng = r.get("engenharia")
    if eng:
        m = q("engenharia", "Sim" if eng == "sim" else "Não")
        inicios_eng = ("ressalvado o objeto ou parte dele sujeito ao regime de empreitada por preco unitario",
                       "para o objeto ou parte dele sujeito ao regime de empreitada por preco unitario",
                       "serao consideradas inexequiveis as propostas cujos valores forem inferiores a 75%",
                       "sera exigida garantia adicional do fornecedor vencedor cuja proposta for inferior a 85%",
                       "em contratacao de obras e servicos de engenharia, alem das disposicoes acima",
                       "anexo ii – projeto basico")
        if eng == "nao":
            a.remover(m, *inicios_eng)
            a.trecho(m, False, "a apresentacao das propostas implica obrigatoriedade", texto_trecho="projeto basico e projeto executivo")
        else:
            a.trecho(m, True, "a apresentacao das propostas implica obrigatoriedade", texto_trecho="projeto basico e projeto executivo")

    # --- Participação ---
    for pid, inicio in (("consorcio", "pessoas juridicas reunidas em consorcio"),
                        ("cooperativas", "sociedades cooperativas"),
                        ("pessoa_fisica", "pessoas fisicas")):
        resp = r.get(pid)
        if not resp:
            continue
        m = q(pid, "Sim" if resp == "sim" else "Não")
        # a cláusula está na lista de quem NÃO pode participar: admitir = tirar da lista
        (a.remover if resp == "sim" else a.manter)(m, inicio)
        if pid == "consorcio" and resp == "nao":
            a.remover(m, "se o consorcio nao for formado integralmente por microempresas")

    # --- Planilha de custos ---
    if r.get("planilha"):
        m = q("planilha", "Sim" if r["planilha"] == "sim" else "Não")
        (a.manter if r["planilha"] == "sim" else a.remover)(
            m, "alem da documentacao supracitada, o fornecedor com a melhor proposta devera encaminhar planilha",
            "anexo iv - planilha de custos e formacao de precos")

    # --- ME/EPP ---
    me = r.get("me_epp_itens")
    if me:
        m = q("me_epp_itens", {"todos": "em todos os itens", "alguns": "só em alguns itens", "nenhum": "em nenhum item"}[me])
        if me == "nenhum":
            # sem exclusividade por item, mas o tratamento favorecido geral às ME/EPP continua
            # (como no Aviso 75/2026 da SJGO: vira o item que antes era o da exclusividade)
            a.manter(m, "sera concedido tratamento favorecido para as microempresas")
            a.remover(m, "para os itens xx", "a obtencao do beneficio a que se refere o item anterior")
        elif me == "todos":
            for b in a.blocos("para os itens xx"):
                novo = re.sub(r"^Para os itens XX(?:,\s*XX)*(?:\s*e\s*XX)?,\s*a participação", "A participação", b.texto.strip())
                if novo != b.texto.strip():
                    a.d.textos.setdefault(b.id, novo)
                    a.d.origem.setdefault(b.id, "questionario")
                    a.d.motivos.setdefault(b.id, m)
            a.manter(m, "a obtencao do beneficio a que se refere o item anterior",
                     "sera concedido tratamento favorecido para as microempresas")
        if me in ("todos", "nenhum"):
            a.remover(m, "nos itens xx, xx e xx nao sera concedido")

    # --- Edital ---
    if r.get("objeto_bens"):
        m = q("objeto_bens", "Compra de bens" if r["objeto_bens"] == "bens" else "Serviço")
        (a.manter if r["objeto_bens"] == "bens" else a.remover)(m, "marca;", "fabricante;")
    sig = r.get("orcamento_sigiloso")
    if sig:
        m = q("orcamento_sigiloso", "Sim" if sig == "sim" else "Não")
        a.manter(m, "do orcamento estimado")
        (a.manter if sig == "nao" else a.remover)(m, "o orcamento estimado da presente contratacao nao sera de carater sigiloso")
        (a.remover if sig == "nao" else a.manter)(
            m, "o orcamento estimado da presente contratacao sera de carater sigiloso",
            "para fins do disposto no item anterior, o orcamento estimado", "o carater sigiloso do orcamento estimado")
    if r.get("vistoria"):
        m = q("vistoria", "Sim" if r["vistoria"] == "sim" else "Não")
        (a.manter if r["vistoria"] == "sim" else a.remover)(
            m, "considerando que na presente contratacao a avaliacao previa do local de execucao")
    return a.d
