"""
Monta a minuta final a partir do modelo da AGU e das decisões do caso.

Tudo o que não foi decidido é copiado literalmente do modelo. Cada diferença em
relação ao modelo fica registrada (bloco alterado, removido e por quê), para que a
revisão do servidor se concentre só no que mudou — em vez de conferir o documento
inteiro linha por linha.

Regras automáticas:
- temas da AGU que não se aplicam (registro de preços, margem de preferência, mão de
  obra exclusiva, engenharia) saem: o bloco inteiro, ou só o trecho realçado;
- a numeração é refeita depois das exclusões, e as referências internas
  ("item 3.3.6", "itens 3.3.4 e 3.3.5") passam a apontar para o novo número;
- separadores "OU" saem; se as duas alternativas ficaram, vira pendência;
- texto variável da AGU (vermelho) que ninguém preencheu vira pendência;
- alteração em texto fixo (preto) é sinalizada: pela orientação da AGU, precisa de
  justificativa nos autos.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace

from app.modelo import NOMES_TEMAS, Bloco, Modelo, Trecho, numerar

TEMAS_PADRAO_EXCLUIDOS = {"registro_precos", "margem_preferencia", "mao_de_obra_exclusiva", "engenharia"}

# "item 3.3.6", "itens 3.3.4 e 3.3.5", "subitem 6.2.", "itens 5.1 a 5.3"
_REFERENCIA = re.compile(
    r"\b((?:sub)?(?:itens|item)|cl[áa]usulas?)\s+(\d+(?:\.\d+)+\.?(?:\s*(?:,|e|a|ou)\s*\d+(?:\.\d+)+\.?)*)",
    re.IGNORECASE)
_NUMERO = re.compile(r"\d+(?:\.\d+)+")
# Marcadores que a AGU às vezes deixa em preto: "itens XX, XX e XX", "Multa de .......%", "nº ....../20..."
MARCADOR_PRETO = re.compile(r"\b[Xx]{2,}\b|\.{4,}")


@dataclass
class Decisoes:
    temas: set[str] = field(default_factory=set)              # temas da AGU que SE APLICAM ao caso
    remover: dict[str, str] = field(default_factory=dict)     # id do bloco → motivo
    textos: dict[str, str] = field(default_factory=dict)      # id do bloco → novo texto (texto simples)
    motivos: dict[str, str] = field(default_factory=dict)     # id do bloco → motivo da alteração
    origem: dict[str, str] = field(default_factory=dict)      # id (bloco ou campo) → "formulario" | "ia" | "servidor"
    campos: dict[str, str] = field(default_factory=dict)      # id do campo ("B035.2") → valor
    manter: set[str] = field(default_factory=set)             # cláusulas vermelhas que ficam (decidido)

    def juntar(self, outra: "Decisoes") -> "Decisoes":
        """Junta decisões (ex.: formulário + IA); as de `outra` prevalecem."""
        return Decisoes(temas=self.temas | outra.temas, remover={**self.remover, **outra.remover},
                        textos={**self.textos, **outra.textos}, motivos={**self.motivos, **outra.motivos},
                        origem={**self.origem, **outra.origem}, campos={**self.campos, **outra.campos},
                        manter=self.manter | outra.manter)


@dataclass
class BlocoFinal:
    id: str
    tipo: str
    nivel: int | None
    numero: str                 # numeração nova ("" se não numerado)
    numero_modelo: str          # numeração no modelo da AGU
    trechos: list[Trecho]
    alinhamento: str
    linhas: list[list[str]]
    situacao: str               # "igual" | "alterado" | "referencia" (só número de item citado mudou)
    texto_modelo: str
    motivo: str = ""
    origem: str = ""
    alterou_texto_fixo: bool = False
    referencias: list[str] = field(default_factory=list)   # "3.3.6 → 2.3.6"

    @property
    def texto(self) -> str:
        if self.tipo == "tabela":
            return "\n".join(" | ".join(c) for c in self.linhas)
        return "".join(t.texto for t in self.trechos)


@dataclass
class Removido:
    id: str
    numero_modelo: str
    texto: str
    motivo: str


@dataclass
class Pendencia:
    bloco: str
    numero: str
    descricao: str
    tipo: str = "campo"         # "campo" | "marcador" | "clausula" | "alternativa" | "referencia"
    relacionado: str = ""       # alternativa: o outro bloco ("OU"); referencia: número citado


@dataclass
class Minuta:
    modelo: Modelo
    blocos: list[BlocoFinal]
    removidos: list[Removido]
    pendencias: list[Pendencia]
    sumario_antes: str | None = None    # id do bloco antes do qual vai o sumário (onde ele estava no modelo)

    @property
    def titulos(self) -> list[BlocoFinal]:
        return [b for b in self.blocos if b.tipo == "titulo"]


def _sem_temas(trechos: list[Trecho], excluidos: set[str]) -> list[Trecho]:
    """Tira os trechos realçados de temas que não se aplicam. Uma sequência realçada que
    contém campo a preencher fica: a AGU às vezes realça "XX (valor por extenso) dias" no meio
    da frase, e tirar isso quebraria o texto (o campo é preenchido normalmente)."""
    saida, i = [], 0
    while i < len(trechos):
        t = trechos[i]
        if not (t.tema and t.tema in excluidos):
            saida.append(copy.copy(t)); i += 1
            continue
        j = i
        while j + 1 < len(trechos) and trechos[j + 1].tema == t.tema:
            j += 1
        grupo = trechos[i:j + 1]
        if any(x.variavel and x.texto.strip() for x in grupo):
            saida.extend(copy.copy(x) for x in grupo)
        i = j + 1
    return saida


def _limpa_espacos(trechos: list[Trecho]) -> list[Trecho]:
    """Depois de tirar um trecho do meio: sem espaço duplo, sem vírgula dupla
    ("Dispensa Eletrônica,, com critério") e sem espaço antes de pontuação."""
    texto = "".join(t.texto for t in trechos)
    limpo = re.sub(r" {2,}", " ", texto)
    limpo = re.sub(r",(\s*,)+", ",", limpo)
    limpo = re.sub(r"[ \t]+([,.;:])", r"\1", limpo)
    return trechos if limpo == texto else _reaplicar_texto(trechos, limpo)


def _ajustar_referencias(texto: str, antigo_para_novo: dict[str, str | None]) -> tuple[str, list[str], list[str]]:
    """Troca "item 3.3.6" pelo número novo. Retorna (texto, trocas feitas, referências a itens removidos)."""
    trocas, quebradas = [], []

    def troca_numero(m: re.Match) -> str:
        antigo = m.group(0)
        chave = antigo.rstrip(".") + "."
        if chave not in antigo_para_novo:
            return antigo
        novo = antigo_para_novo[chave]
        if novo is None:
            quebradas.append(antigo.rstrip("."))
            return antigo
        novo = novo.rstrip(".")
        if novo != antigo.rstrip("."):
            trocas.append(f"{antigo.rstrip('.')} → {novo}")
        return novo + ("." if antigo.endswith(".") and not novo.endswith(".") else "")

    def troca_grupo(m: re.Match) -> str:
        return m.group(1) + " " + _NUMERO.sub(troca_numero, m.group(2))

    return _REFERENCIA.sub(troca_grupo, texto), trocas, quebradas


def montar(modelo: Modelo, decisoes: Decisoes) -> Minuta:
    excluidos = TEMAS_PADRAO_EXCLUIDOS - set(decisoes.temas)
    numeros_modelo = numerar(modelo.blocos)
    mantidos: list[tuple[Bloco, list[Trecho]]] = []
    removidos: list[Removido] = []
    pendencias: list[Pendencia] = []

    corte: tuple[int, str] | None = None     # (nível, número) do item removido: seus subitens saem junto
    for b in modelo.blocos:
        if b.tipo == "sumario":
            continue                                  # o sumário é refeito a partir dos títulos finais
        num = numeros_modelo.get(b.id, "")
        if corte is not None:
            if b.nivel and b.nivel > corte[0] and (b.id in decisoes.manter or b.id in decisoes.textos):
                # subitem que fica por decisão própria: sobe para o lugar do item removido
                # (ex.: "Será concedido tratamento favorecido às ME/EPP" sem a exclusividade por item)
                b = replace(b, nivel=b.nivel - (b.nivel - corte[0]))
                corte = None
            elif b.nivel and b.nivel > corte[0] or b.tipo == "tabela":
                removidos.append(Removido(b.id, num, b.texto, f"Subitem do item {corte[1]} do modelo, que foi removido"))
                continue
            elif b.tipo != "ou":
                corte = None
        if b.tema_integral and b.tema_integral in excluidos and b.id not in decisoes.textos and b.id not in decisoes.manter:
            # (bloco reescrito ou mantido por decisão não sai pelo tema: ex. valor do OBJETO na capa,
            # que a AGU realça como registro de preços)
            removidos.append(Removido(b.id, num, b.texto, f"{NOMES_TEMAS[b.tema_integral]}: não se aplica ao caso"))
            continue
        if b.id in decisoes.remover:
            removidos.append(Removido(b.id, num, b.texto, decisoes.remover[b.id] or "Removido"))
            if b.nivel:
                corte = (b.nivel, num.rstrip("."))
            continue
        restantes = _sem_temas(b.trechos, excluidos)
        if len(restantes) != len(b.trechos):
            restantes = _limpa_espacos(restantes)
        mantidos.append((b, restantes))

    # Título que ficou sem nenhum item embaixo (todos removidos) sai também
    filtrados = []
    for i, (b, tr) in enumerate(mantidos):
        if b.tipo == "titulo":
            proximo = mantidos[i + 1][0] if i + 1 < len(mantidos) else None
            if proximo is None or proximo.tipo == "titulo":
                removidos.append(Removido(b.id, numeros_modelo.get(b.id, ""), b.texto, "Seção ficou vazia"))
                continue
        filtrados.append((b, tr))
    mantidos = filtrados

    # Separadores "OU": saem; se as alternativas dos dois lados (vizinhas no MODELO) ficaram,
    # alguém precisa escolher uma delas
    ficaram = {b.id for b, _ in mantidos}
    posicao = {b.id: i for i, b in enumerate(modelo.blocos)}
    finais_brutos: list[tuple[Bloco, list[Trecho]]] = []
    for b, tr in mantidos:
        if b.tipo == "ou":
            i = posicao[b.id]
            antes = next((x for x in reversed(modelo.blocos[:i]) if x.tipo != "sumario"), None)
            depois = next((x for x in modelo.blocos[i + 1:] if x.tipo != "sumario"), None)
            if (antes is not None and depois is not None and antes.id in ficaram and depois.id in ficaram
                    and antes.tipo != "titulo" and depois.tipo not in ("titulo", "ou")):
                pendencias.append(Pendencia(depois.id, "", "Escolher uma das redações alternativas (o modelo traz \"OU\" entre elas)",
                                            "alternativa", antes.id))
            removidos.append(Removido(b.id, "", b.texto, "Separador \"OU\" do modelo"))
            continue
        finais_brutos.append((b, tr))

    novos_numeros = numerar([b for b, _ in finais_brutos])
    antigo_para_novo: dict[str, str | None] = {}
    for b in modelo.blocos:
        if b.id in numeros_modelo:
            antigo_para_novo[numeros_modelo[b.id]] = novos_numeros.get(b.id)

    blocos: list[BlocoFinal] = []
    for b, trechos in finais_brutos:
        num_novo = novos_numeros.get(b.id, "")
        situacao, motivo, origem, fixo = "igual", "", "", False
        if b.id in decisoes.textos:
            novo_texto = decisoes.textos[b.id]
            trechos = [Trecho(texto=novo_texto, negrito=all(t.negrito for t in b.trechos if t.texto.strip()))]
            situacao, motivo = "alterado", decisoes.motivos.get(b.id, "")
            origem = decisoes.origem.get(b.id, "")
            # Pela AGU, mudar texto preto exige justificativa; o formulário só preenche lacunas da capa
            fixo = not b.tem_variavel and origem != "formulario"
        else:
            if "".join(t.texto for t in trechos) != b.texto:
                situacao, motivo = "alterado", "Trecho de tema que não se aplica foi retirado"
            preenchidos = [c for c in dict.fromkeys(t.campo for t in trechos if t.campo) if c in decisoes.campos]
            if preenchidos:
                trechos = _preencher_campos(trechos, decisoes.campos)
                situacao = "alterado"
                origens = {decisoes.origem.get(c, "") for c in preenchidos}
                origem = origens.pop() if len(origens) == 1 else "misto"
                motivo = "; ".join(m for m in (motivo, decisoes.motivos.get(preenchidos[0], "Campos preenchidos")) if m)

        refs: list[str] = []
        if b.tipo != "tabela":
            texto_atual = "".join(t.texto for t in trechos)
            novo, trocas, quebradas = _ajustar_referencias(texto_atual, antigo_para_novo)
            if trocas:
                trechos = _reaplicar_texto(trechos, novo)
                refs = trocas
                if situacao == "igual":
                    situacao = "referencia"     # só a numeração citada mudou (ajuste automático)
            for q in quebradas:
                pendencias.append(Pendencia(b.id, num_novo, f"Cita o item {q} do modelo, que foi removido", "referencia", q))

        if b.id not in decisoes.textos:
            if b.clausula_vermelha:
                if b.id not in decisoes.manter:
                    pendencias.append(Pendencia(b.id, num_novo, "Cláusula opcional (vermelho na AGU): manter ou remover conforme o caso", "clausula"))
                else:
                    trechos = [_como_fixo(t) for t in trechos]
            elif any(t.variavel and t.texto.strip() for t in trechos):
                pendencias.append(Pendencia(b.id, num_novo, "Campo do modelo ainda não preenchido (texto em vermelho na AGU)"))
            elif MARCADOR_PRETO.search("".join(t.texto for t in trechos)):
                pendencias.append(Pendencia(b.id, num_novo, "Marcador do modelo a preencher (XX / ......)", "marcador"))
            elif b.opcional and b.id not in decisoes.manter and situacao != "alterado":
                # estilo "-R"/"-Opcional" da AGU: redação que se adota ou não (no Aviso 75/2026 a SELIT tirou 2/3)
                pendencias.append(Pendencia(b.id, num_novo, "Cláusula opcional do modelo da AGU: manter ou remover conforme o caso", "opcional"))

        blocos.append(BlocoFinal(
            id=b.id, tipo=b.tipo, nivel=b.nivel, numero=num_novo, numero_modelo=numeros_modelo.get(b.id, ""),
            trechos=trechos, alinhamento=b.alinhamento, linhas=b.linhas, situacao=situacao,
            texto_modelo=b.texto, motivo=motivo, origem=origem, alterou_texto_fixo=fixo, referencias=refs))

    numeros_finais = {bf.id: bf.numero for bf in blocos}
    for pd in pendencias:
        if not pd.numero:
            pd.numero = numeros_finais.get(pd.bloco, "")
    posicao = {x.id: i for i, x in enumerate(modelo.blocos)}
    inicio_sumario = next((i for i, x in enumerate(modelo.blocos) if x.tipo == "sumario"), None)
    sumario_antes = None
    if inicio_sumario is not None:
        sumario_antes = next((bf.id for bf in blocos if posicao[bf.id] > inicio_sumario), None)
    return Minuta(modelo=modelo, blocos=blocos, removidos=removidos, pendencias=pendencias,
                  sumario_antes=sumario_antes)


def _como_fixo(t: Trecho) -> Trecho:
    n = copy.copy(t); n.variavel = False
    return n


MANTER_CAMPO = "__manter__"   # valor especial: o trecho vermelho fica como está no modelo (trecho opcional adotado)


def _preencher_campos(trechos: list[Trecho], valores: dict[str, str]) -> list[Trecho]:
    """Troca cada campo preenchido (todos os seus pedaços) por um trecho só com o valor.
    Valor vazio retira o trecho; MANTER_CAMPO mantém o texto do modelo."""
    saida: list[Trecho] = []
    feitos: set[str] = set()
    for t in trechos:
        if t.campo and valores.get(t.campo) == MANTER_CAMPO:
            saida.append(_como_fixo(t))
            continue
        if t.campo and t.campo in valores:
            if t.campo not in feitos:
                feitos.add(t.campo)
                if valores[t.campo]:
                    # o campo pode incluir o espaço antes/depois ("⟦60 (sessenta)⟧⟦ ⟧dias"): preserva
                    original = "".join(x.texto for x in trechos if x.campo == t.campo)
                    valor = valores[t.campo].strip()
                    antes = " " if original[:1].isspace() else ""
                    depois = " " if original[-1:].isspace() else ""
                    saida.append(Trecho(texto=antes + valor + depois, negrito=t.negrito, sublinhado=t.sublinhado))
            continue
        saida.append(t)
    saida = _limpa_espacos(saida)
    # Modelo da AGU: "para assinar o ⟦Termo de Contrato OU aceitar instrumento equivalente⟧" — escolhida
    # a segunda opção, "assinar o aceitar" não faz sentido
    texto = "".join(t.texto for t in saida)
    corrigido = re.sub(r"\bassinar o (aceitar)\b", r"\1", texto)
    return saida if corrigido == texto else _reaplicar_texto(saida, corrigido)


def _reaplicar_texto(trechos: list[Trecho], novo: str) -> list[Trecho]:
    """Troca o texto mantendo a formatação: só os números de item mudam de tamanho, então
    redistribui caractere a caractere pelos trechos originais quando possível."""
    antigo = "".join(t.texto for t in trechos)
    if len(trechos) == 1:
        t = copy.copy(trechos[0]); t.texto = novo
        return [t]
    # Alinha por blocos iguais (difflib) e devolve cada parte ao trecho de origem
    import difflib
    limites, pos = [], 0
    for t in trechos:
        limites.append((pos, pos + len(t.texto)))
        pos += len(t.texto)
    saida = [""] * len(trechos)

    def dono(i: int) -> int:
        for k, (a, b) in enumerate(limites):
            if a <= i < b:
                return k
        return len(trechos) - 1

    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, antigo, novo, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(a2 - a1):
                saida[dono(a1 + k)] += novo[b1 + k]
        elif op in ("replace", "insert"):
            saida[dono(a1 if a1 < len(antigo) else len(antigo) - 1)] += novo[b1:b2]
    resultado = []
    for t, texto in zip(trechos, saida):
        if texto:
            n = copy.copy(t); n.texto = texto
            resultado.append(n)
    return resultado
