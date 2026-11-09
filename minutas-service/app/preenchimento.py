"""
Preenchimento determinístico: dados fixos da Justiça Federal em Goiás + formulário do caso.

O que é sempre igual (órgão, UASG, endereço, e-mail do setor, fecho com assinatura
eletrônica) e o que o servidor informa no formulário (processo, número, objeto, valor,
datas, critério) não precisa passar pela IA: é preenchido aqui, por regra, sempre do
mesmo jeito. A IA fica só com o que exige leitura do Termo de Referência.

Formato de cada valor tirado das minutas já publicadas pela SJGO (Aviso 75/2026,
Edital 58/2026).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.modelo import Bloco, Modelo
from app.montagem import Decisoes

DADOS_JF = {
    "orgao": "JUSTIÇA FEDERAL DE 1ª INSTÂNCIA/GO",
    "uasg": "090022",
    "setor": "Seção de Contratações Públicas",
    "email": "secop.go@trf1.jus.br",
    "endereco": "Rua 19, nº 244, Setor Central, CEP 74030-090, Goiânia-GO",
    "cidade": "Goiânia",
    "sites": [
        "https://www.trf1.jus.br/sjgo/compras-e-licitacoes-goiania/compras-e-licitacoes-em-andamento--goiania",
        "https://sistemas.trf1.jus.br/licitacoes/",
    ],
    "validade_proposta": "60 (sessenta)",
}


@dataclass
class DadosCaso:
    processo: str = ""            # 0000000-00.2026.4.01.8006
    numero: str = ""              # 1/2026
    objeto: str = ""              # "contratação de empresa especializada para ..."
    valor_total: str = ""         # "10.000,00"
    data_sessao: str = ""         # "21/10/2026"
    hora_sessao: str = ""         # "14h" (edital)
    horario_lances: str = ""      # "Das 08h até 14h" (aviso)
    criterio: str = ""            # "menor preço global"
    modo_disputa: str = ""        # "aberto" (edital)
    me_epp: str = ""              # "SIM" | "NÃO" | texto com a justificativa
    margem_preferencia: str = "NÃO"
    inciso: str = ""              # inciso do art. 75 (aviso): "I" | "II"
    signatario: str = ""          # nome de quem assina
    cargo: str = ""
    # Dados da JF (padrão em DADOS_JF; o servidor pode ajustar)
    orgao: str = DADOS_JF["orgao"]
    uasg: str = DADOS_JF["uasg"]
    setor: str = DADOS_JF["setor"]
    email: str = DADOS_JF["email"]
    endereco: str = DADOS_JF["endereco"]
    cidade: str = DADOS_JF["cidade"]
    sites: list[str] = field(default_factory=lambda: list(DADOS_JF["sites"]))
    validade_proposta: str = DADOS_JF["validade_proposta"]


def _n(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def _primeira_maiuscula(t: str) -> str:
    return t[:1].upper() + t[1:] if t else t


def _primeira_minuscula(t: str) -> str:
    # não rebaixa sigla ("SICAF") nem nome próprio em maiúsculas
    return t[:1].lower() + t[1:] if t[:2] and not t[:2].isupper() else t


def preencher(modelo: Modelo, dados: DadosCaso, temas: set[str] | None = None) -> Decisoes:
    """Decisões que saem do formulário e dos dados fixos (origem "formulario")."""
    d = Decisoes(temas=set(temas or set()))
    edital = modelo.tipo == "edital_pregao"
    com_rp = "registro_precos" in d.temas

    def campo(cid: str, valor: str, motivo: str) -> None:
        if valor:
            d.campos[cid] = valor
            d.origem[cid] = "formulario"
            d.motivos.setdefault(cid, motivo)

    def texto(bid: str, valor: str, motivo: str) -> None:
        if valor:
            d.textos[bid] = valor
            d.origem[bid] = "formulario"
            d.motivos[bid] = motivo

    blocos = [b for b in modelo.blocos if b.tipo != "sumario"]
    corpo_inicio = next((i for i, b in enumerate(blocos) if _n(b.texto) in ("modelo de edital",)
                         or _n(b.texto).startswith("orgao ou entidade publica")), len(blocos))

    # ---- Capa (rótulo em um parágrafo, valor no seguinte; marcadores em preto) ----
    def proximo(i: int) -> Bloco | None:
        return blocos[i + 1] if i + 1 < len(blocos) else None

    for i, b in enumerate(blocos[:corpo_inicio]):
        t = _n(b.texto)
        prox = proximo(i)
        if re.fullmatch(r"x{2,}/x{2,}", t):
            texto(b.id, dados.numero, "Número (formulário)")
        elif re.fullmatch(r"\[?concorrencia\]? ou \[?pregao eletronico\]?", t):
            texto(b.id, "PREGÃO ELETRÔNICO", "Modalidade")
        elif t.startswith("contratante/gerenciador"):
            if not com_rp:
                texto(b.id, "CONTRATANTE (UASG)", "Sem registro de preços: não há órgão gerenciador")
            if prox is not None:
                texto(prox.id, f"{dados.orgao} ({dados.uasg})", "Dados fixos da JF")
        elif t == "objeto" and prox is not None:
            texto(prox.id, _primeira_maiuscula(dados.objeto), "Objeto (formulário)")
        elif t.startswith("valor total da contratacao") and prox is not None and dados.valor_total:
            texto(prox.id, "R$ " + dados.valor_total.removeprefix("R$").strip(), "Valor (formulário)")
        elif t.startswith("data da sessao publica") and prox is not None and dados.data_sessao:
            if edital:
                valor = f"Dia {dados.data_sessao}" + (f" às {dados.hora_sessao}" if dados.hora_sessao else "") + " (horário de Brasília)"
            else:
                valor = f"De {dados.data_sessao}"
            texto(prox.id, valor, "Data da sessão (formulário)")
        elif t.startswith("horario da fase de lances") and prox is not None:
            texto(prox.id, dados.horario_lances, "Horário dos lances (formulário)")
        elif t.startswith("criterio de julgamento") and prox is not None:
            texto(prox.id, _primeira_maiuscula(dados.criterio), "Critério (formulário)")
        elif t.startswith("modo de disputa") and prox is not None:
            texto(prox.id, _primeira_maiuscula(dados.modo_disputa), "Modo de disputa (formulário)")
        elif t.startswith("tratamento favorecido me/epp"):
            rotulo = b.texto.split("\n")[0].strip()
            if "\n" in b.texto:      # aviso: rótulo e valor no mesmo parágrafo
                texto(b.id, f"{rotulo}\n{dados.me_epp}" if dados.me_epp else "", "ME/EPP (formulário)")
            elif prox is not None:
                texto(prox.id, dados.me_epp, "ME/EPP (formulário)")
        elif t.startswith("margem de preferencia para algum item") and prox is not None:
            texto(prox.id, dados.margem_preferencia, "Margem de preferência (formulário)")

    # ---- Corpo ----
    for b in blocos[corpo_inicio:]:
        t = _n(b.texto)
        if t == "modelo de edital":
            texto(b.id, "EDITAL", "Título do documento")
            continue
        if t.startswith("(processo administrativo n"):
            texto(b.id, f"(Processo Administrativo n° {dados.processo})" if dados.processo else "", "Processo (formulário)")
            continue
        if edital and re.match(r"\[?concorrencia\]? ou \[?pregao eletronico\]? n", t):
            texto(b.id, f"PREGÃO ELETRÔNICO Nº {dados.numero}" if dados.numero else "", "Número (formulário)")
            continue
        if re.fullmatch(r"\[?local\]?, \[?dia\]? de \[?mes\]? de \[?ano\]?\.?", t):
            texto(b.id, f"{dados.cidade}, data e horário da assinatura eletrônica.", "Fecho padrão da SJGO")
            continue
        for c in b.campos:
            ct = _n(c.texto).strip("[] ")
            if ct == "orgao ou entidade publica":
                campo(c.id, dados.orgao, "Dados fixos da JF")
            elif ct.startswith("setor responsavel"):
                campo(c.id, dados.setor, "Dados fixos da JF")
            elif ct == "endereco":
                campo(c.id, dados.endereco + (f", e-mail: {dados.email}" if dados.email and not edital else ""), "Dados fixos da JF")
            elif re.fullmatch(r"x{2,}/a{2,}", ct):
                campo(c.id, dados.numero, "Número (formulário)")
            elif re.fullmatch(r"x+\.x+/x+-x+", ct):
                campo(c.id, dados.processo, "Processo (formulário)")
            elif ct == "objeto":
                campo(c.id, _primeira_minuscula(dados.objeto), "Objeto (formulário)")
            elif edital and c.opcoes and {_n(o) for o in c.opcoes} == {"concorrencia", "pregao eletronico"}:
                campo(c.id, "PREGÃO ELETRÔNICO", "Modalidade")
            elif c.opcoes and {_n(o) for o in c.opcoes} == {"menor preco", "maior desconto"}:
                campo(c.id, dados.criterio, "Critério (formulário)")
            elif ct.startswith("inciso") and dados.inciso:
                campo(c.id, f"inciso {dados.inciso}", "Hipótese do art. 75 (formulário)")
            elif "validade da proposta" in t and (re.fullmatch(r"x{2} \(valor por extenso\)", ct) or re.search(r"\d", ct)):
                campo(c.id, dados.validade_proposta, "Prazo padrão da SJGO")
            elif ct == "assinatura da autoridade competente" and dados.signatario:
                fecho = "" if edital else f"{dados.cidade}, data e horário da assinatura eletrônica.\n"
                campo(c.id, fecho + dados.signatario + (f"\n{dados.cargo}" if dados.cargo else ""), "Assinatura (formulário)")
            elif "inserir endereco eletronico" in ct and "disponiveis, na integra" in t:
                campo(c.id, " e ".join(dados.sites), "Sites de licitações da JF")
            elif ct.startswith("indicar os meios") and dados.email:
                campo(c.id, f"endereço eletrônico {dados.email}", "E-mail do setor")
    return d
