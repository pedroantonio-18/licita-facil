"""
Regras de enquadramento da despesa (Lei 14.133/2021, LC 123/2006, IN SEGES/ME 67/2021).

Tudo determinístico: o sistema calcula e aponta; quem decide e assina é o servidor.

- Limite da dispensa por valor (art. 75): inciso I para obras e serviços de engenharia e
  manutenção de veículos automotores; inciso II para as demais compras e serviços.
  Valores atualizados por decreto a cada ano (Decreto nº 12.807/2025 para 2026).
- Fracionamento (art. 4º da IN 67/2021): soma-se o valor estimado com as demandas
  semelhantes do PCA do exercício (mesmo PDM para materiais, mesma descrição para
  serviços) e com o que já foi contratado no exercício por dispensa. Se a soma passa do
  limite, a licitação é obrigatória.
- ME/EPP (art. 48, I, da LC 123/2006): item de até R$ 80.000,00 → participação exclusiva;
  acima disso → ampla participação.
- Dispensa com possível contratação de pessoa física: informa-se o valor de 20% da
  Seguridade Social (art. 5º, III, da IN SEGES/ME nº 116/2021).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

# Limites por exercício (Decreto nº 12.807/2025, publicado em 30/12/2025; valores confirmados pela
# SELIT). O decreto é atualizado todo fim de ano: enquanto o do exercício seguinte não sai, vale o
# último publicado. Pode ser substituído por arquivo JSON (ENQUADRAMENTO_LIMITES).
LIMITES_PADRAO = {
    "2026": {"I": "130984.20", "II": "65492.11", "decreto": "Decreto nº 12.807/2025"},
}
LIMITE_ME_EPP = Decimal("80000.00")
# Acima da receita bruta máxima de EPP não há tratamento favorecido (art. 4º, § 1º, I, da Lei 14.133/2021)
TETO_EPP = Decimal("4800000.00")
SEGURIDADE = Decimal("0.20")

NATUREZAS = {
    "bem": "Aquisição de bens",
    "servico": "Serviço comum",
    "servico_engenharia": "Serviço comum de engenharia",
    "manutencao_veiculos": "Manutenção de veículos automotores",
    "obra": "Obra",
}
INCISO_I = {"servico_engenharia", "manutencao_veiculos", "obra"}


def limites() -> dict:
    caminho = os.environ.get("ENQUADRAMENTO_LIMITES")
    if caminho and Path(caminho).is_file():
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    return LIMITES_PADRAO


@dataclass
class Item:
    descricao: str
    valor: Decimal
    divisivel: bool = False   # bem divisível (ex.: 100 cadeiras): acima de R$ 80 mil admite cota reservada


@dataclass
class Demanda:
    """Demanda semelhante do PCA ou contratação já realizada no exercício."""
    descricao: str
    origem: str          # ex.: "Dispensa (art. 75, II)", "PCA", "Nota de Empenho 2026NE000318"
    valor: Decimal
    ja_contratada: bool = False
    propria: bool = False   # é a própria demanda destes autos (aparece na tabela, mas não soma duas vezes)


@dataclass
class Enquadramento:
    modalidade: str                  # "dispensa" | "pregao" | "concorrencia"
    inciso: str                      # "I" | "II" (da dispensa)
    limite: Decimal
    decreto: str
    limite_confirmado: bool
    exercicio: str
    valor_estimado: Decimal
    soma_exercicio: Decimal          # estimado + demandas semelhantes do PCA + já contratado
    fracionamento_ok: bool
    # {"regra": "exclusiva"|"ampla"|"mista", "exclusivos": [...], "cotas": [...], "amplos": [...], "sem_beneficio": [...]}
    me_epp: dict
    seguridade: Decimal | None       # 20% (só dispensa)
    avisos: list[str] = field(default_factory=list)


def enquadrar(natureza: str, itens: list[Item], demandas: list[Demanda], exercicio: str,
              forcar_licitacao: bool = False, grupo_unico: bool = False) -> Enquadramento:
    if natureza not in NATUREZAS:
        raise ValueError(f"Natureza desconhecida: {natureza}")
    if not itens:
        raise ValueError("Informe ao menos um item com valor")
    tabela = limites()
    avisos: list[str] = []
    if exercicio not in tabela:
        anteriores = sorted((a for a in tabela if a < exercicio), reverse=True)
        if not anteriores:
            raise ValueError(f"Limite de dispensa do exercício {exercicio} não cadastrado")
        # Enquanto não sai o decreto do ano, vale o último limite ("atualmente de R$ 65.492,11")
        avisos.append(f"Limite de {exercicio} ainda não cadastrado: usado o de {anteriores[0]} ({tabela[anteriores[0]].get('decreto', '')}).")
        lim = tabela[anteriores[0]]
    else:
        lim = tabela[exercicio]
    inciso = "I" if natureza in INCISO_I else "II"
    limite = Decimal(lim[inciso])
    confirmado = lim.get(f"confirmado_{inciso}", True)
    if not confirmado:
        avisos.append(f"Limite do art. 75, inciso {inciso}, para {exercicio} ainda não confirmado com a SELIT.")

    valor = sum((i.valor for i in itens), Decimal("0"))
    soma = valor + sum((d.valor for d in demandas if not d.propria), Decimal("0"))
    dentro = soma <= limite

    if natureza == "obra":
        modalidade = "dispensa" if dentro and not forcar_licitacao else "concorrencia"
        if modalidade == "concorrencia":
            avisos.append("Obra acima do limite da dispensa: concorrência (fora dos modelos de Informação da SELIT).")
    else:
        modalidade = "dispensa" if dentro and not forcar_licitacao else "pregao"
    if not dentro and modalidade != "dispensa":
        if valor > limite:
            avisos.append("O valor estimado passa do limite da dispensa: a licitação é obrigatória.")
        else:
            avisos.append("Somadas as demandas semelhantes do exercício, o limite da dispensa é ultrapassado: "
                          "a licitação é obrigatória (art. 4º da IN SEGES/ME nº 67/2021).")

    # ME/EPP (LC 123/2006, art. 48; regras confirmadas pela SELIT):
    # - dispensa por valor: exclusiva para ME/EPP em todos os itens;
    # - licitação, item a item: até R$ 80 mil → exclusivo (inciso I); acima e divisível → cota reservada
    #   de até 25% (inciso III); acima e indivisível → ampla participação; acima de R$ 4,8 milhões → sem
    #   tratamento favorecido;
    # - grupo/lote único: vale o valor do grupo inteiro (art. 9º, § 1º, do Decreto nº 8.538/2015).
    exclusivos, cotas, amplos, sem_beneficio = [], [], [], []
    if modalidade == "dispensa":
        exclusivos = list(itens)
    elif grupo_unico:
        (exclusivos if valor <= LIMITE_ME_EPP else amplos).extend(itens)
        if valor > LIMITE_ME_EPP and any(i.valor <= LIMITE_ME_EPP for i in itens):
            avisos.append("Grupo único acima de R$ 80.000,00: nem os itens menores são exclusivos para ME/EPP "
                          "(conta o valor do grupo — art. 9º, § 1º, do Decreto nº 8.538/2015).")
    else:
        for i in itens:
            if i.valor > TETO_EPP:
                sem_beneficio.append(i)
            elif i.valor <= LIMITE_ME_EPP:
                exclusivos.append(i)
            elif i.divisivel:
                cotas.append(i)
            else:
                amplos.append(i)
    if cotas:
        avisos.append("Cota reservada (até 25%): o percentual é definido motivadamente pelo setor requisitante; não se aplica "
                      "se não houver ao menos 3 ME/EPP competitivas ou se a divisão trouxer prejuízo (art. 49, II e III, da LC 123/2006).")
    if sem_beneficio:
        avisos.append("Item acima de R$ 4.800.000,00: sem tratamento favorecido para ME/EPP (art. 4º, § 1º, I, da Lei 14.133/2021).")
    grupos = sum(bool(g) for g in (exclusivos, cotas, amplos or sem_beneficio))
    regra = "mista" if grupos > 1 or cotas else ("exclusiva" if exclusivos else "ampla")
    nomes = lambda lista: [i.descricao for i in lista]

    return Enquadramento(
        modalidade=modalidade, inciso=inciso, limite=limite, decreto=lim.get("decreto", ""),
        limite_confirmado=confirmado, exercicio=exercicio, valor_estimado=valor, soma_exercicio=soma,
        fracionamento_ok=dentro,
        me_epp={"regra": regra, "exclusivos": nomes(exclusivos), "cotas": nomes(cotas), "amplos": nomes(amplos),
                "sem_beneficio": nomes(sem_beneficio)},
        seguridade=(valor * SEGURIDADE).quantize(Decimal("0.01")) if modalidade == "dispensa" else None,
        avisos=avisos,
    )
