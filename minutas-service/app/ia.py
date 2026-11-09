"""
Sugestões da IA (Gemini) para as pendências da minuta, a partir do Termo de Referência.

Padrão de relé do Licita Fácil: o servidor monta o pedido (prompt), o navegador chama o
Gemini e devolve a resposta crua, e o servidor valida cada sugestão antes de aplicar.

A IA só decide o que ficou pendente depois do formulário — o resto do modelo da AGU é
copiado literalmente. Regras de validação (sugestão que falha é descartada, com o motivo):
- só blocos pendentes e ações compatíveis com o tipo de pendência;
- motivo obrigatório; preencher, reescrever ou manter cláusula opcional exige um trecho
  literal do TR como evidência, e o trecho precisa existir no TR enviado;
- valores sem marcadores do modelo ("XX", "[...]"); escolha precisa ser uma das opções;
- reescrita não pode trocar o texto da AGU por outro completamente diferente.
Decisões já tomadas pelo servidor prevalecem: a IA não recebe esses blocos.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.montagem import MANTER_CAMPO, MARCADOR_PRETO, BlocoFinal, Decisoes, Minuta
from app.modelo import Modelo

# Lacuna a preencher (inclui valor sugerido pela AGU, ex. "60 (sessenta)", "2 (duas) horas", "0,5%");
# o resto do texto vermelho é trecho opcional (manter ou retirar)
LACUNA = re.compile(r"\[|\b[Xx]{2,}\b|\.{3,}|\d|valor por extenso|inserir|indicar", re.IGNORECASE)
# Valor que ainda tem marcador do modelo (não pode ser aceito como preenchimento)
COM_MARCADOR = re.compile(r"\[|\]|\b[Xx]{2,}\b|\.{3,}|valor por extenso", re.IGNORECASE)
MAX_TR = 250_000          # caracteres do TR no prompt (~60 mil tokens)
MIN_MOTIVO = 15

ACOES_POR_TIPO = {
    "campo": {"preencher", "manter_trecho", "retirar_trecho", "remover", "reescrever"},
    "clausula": {"manter", "remover"},
    "opcional": {"manter", "remover"},
    "alternativa": {"manter", "remover"},
    "marcador": {"reescrever", "remover"},
    "referencia": {"reescrever", "remover"},
}
EXIGE_EVIDENCIA = {"preencher", "reescrever", "manter", "manter_trecho"}


def _n(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w%$,.;:/()-]", " ", t)).strip()


def _texto_marcado(b: BlocoFinal) -> str:
    """Texto do bloco com cada campo pendente marcado: ⟦B105.1: [valor unitário] OU [...]⟧."""
    partes, vistos = [], set()
    for t in b.trechos:
        if t.campo and t.variavel:
            if t.campo in vistos:
                continue
            vistos.add(t.campo)
            texto = "".join(x.texto for x in b.trechos if x.campo == t.campo)
            partes.append(f"⟦{t.campo}: {texto.strip()}⟧")
        else:
            partes.append(t.texto)
    return "".join(partes)


@dataclass
class ItemPendente:
    bloco: str
    numero: str
    tipo: str
    descricao: str
    texto: str
    campos: list[dict]
    notas: list[str]
    alternativa: dict | None = None

    @property
    def acoes(self) -> set[str]:
        return ACOES_POR_TIPO.get(self.tipo, {"remover"})


def pendencias_para_ia(modelo: Modelo, minuta: Minuta, decididos: set[str]) -> list[ItemPendente]:
    """Pendências que a IA pode resolver (exclui blocos que o servidor já decidiu)."""
    blocos = {b.id: b for b in minuta.blocos}
    modelo_blocos = {b.id: b for b in modelo.blocos}
    itens = []
    for p in minuta.pendencias:
        b = blocos.get(p.bloco)
        if b is None or p.bloco in decididos or (p.relacionado and p.relacionado in decididos):
            continue
        campos = []
        for c in modelo_blocos[b.id].campos:
            if not any(t.campo == c.id and t.variavel for t in b.trechos):
                continue                                    # já preenchido pelo formulário
            tipo = "escolha" if c.opcoes else ("lacuna" if LACUNA.search(c.texto) else "trecho_opcional")
            campo = {"id": c.id, "texto": c.texto, "tipo": tipo, "opcoes": c.opcoes}
            if POR_EXTENSO.search(c.texto):
                campo["formato"] = "número seguido do extenso entre parênteses, ex.: 30 (trinta) ou R$ 100,00 (cem reais)"
            campos.append(campo)
        alternativa = None
        if p.tipo == "alternativa" and p.relacionado in blocos:
            alternativa = {"bloco": p.relacionado, "texto": blocos[p.relacionado].texto}
        itens.append(ItemPendente(p.bloco, b.numero, p.tipo, p.descricao, _texto_marcado(b), campos,
                                  modelo_blocos[b.id].notas, alternativa))
    return itens


INSTRUCOES = """Você vai ajudar a SELIT da Justiça Federal em Goiás a finalizar uma minuta de {tipo_nome}
elaborada a partir do modelo oficial da AGU (versão {versao}). O modelo foi usado no sentido literal:
o sistema já copiou o texto da AGU, preencheu os dados do formulário e retirou os temas que não se aplicam.
Restam as PENDÊNCIAS abaixo. Para cada uma, decida com base EXCLUSIVAMENTE no Termo de Referência
(e demais anexos) enviados, seguindo as notas explicativas da AGU no que forem aplicáveis.

Regras:
1. Mexa apenas nos blocos listados. Não invente informação: se o TR não permitir decidir, coloque o
   bloco em "sem_informacao" com o motivo (o servidor decidirá). O silêncio do TR NÃO justifica remover
   cláusula do modelo: só remova quando o TR indicar que ela não se aplica, citando esse trecho.
   Nunca crie valores (percentuais, prazos, quantias) que não estejam no TR.
2. Toda decisão precisa de "motivo" (frase curta). Para "preencher", "reescrever", "manter" e
   "manter_trecho", copie em "evidencia" um trecho LITERAL do TR (até 300 caracteres) que sustenta a decisão —
   ele será conferido no documento; trecho que não existir no TR invalida a sugestão.
3. Ações possíveis por bloco (use só as permitidas em "acoes"):
   - "preencher": dê o valor de cada campo em "campos" ({{"ID_DO_CAMPO": "valor"}}). Campo "escolha":
     o valor deve ser uma das opções. Campo "lacuna": escreva o valor no padrão do modelo
     (ex.: "5 (cinco)"). Não deixe colchetes nem "XX".
   - "manter_trecho" / "retirar_trecho": para campo "trecho_opcional" (informe "campo").
   - "manter" / "remover": cláusula opcional inteira; nas alternativas "OU", "manter" fica com
     aquela redação e a outra sai. Atenção ao sentido: numa lista de quem NÃO pode participar,
     remover um item significa permitir a participação. Ao remover um item, os subitens saem junto.
   - "reescrever": texto completo e final do bloco em "texto", alterando só o necessário (sem a numeração).
     Não reescreva para negar a cláusula ou dizer que não se aplica: nesse caso use "remover".
4. Preserve a redação da AGU: não reescreva o que não precisa mudar.
5. Linguagem formal; não acrescente cláusulas novas.

Dados do caso (já aplicados na minuta): {dados}

Responda SOMENTE com JSON neste formato:
{{"decisoes": [{{"bloco": "B105", "acao": "preencher", "campos": {{"B105.1": "valor unitário"}},
                 "campo": "", "texto": "", "motivo": "...", "evidencia": "..."}}],
  "sem_informacao": [{{"bloco": "B108", "motivo": "o TR não fixa ..."}}]}}

PENDÊNCIAS:
{pendencias}

TERMO DE REFERÊNCIA E ANEXOS:
<<<
{tr}
>>>
"""


def montar_prompt(modelo: Modelo, itens: list[ItemPendente], texto_tr: str, dados: dict, tipo_nome: str) -> str:
    catalogo = []
    for it in itens:
        catalogo.append({
            "bloco": it.bloco, "numero": it.numero, "pendencia": it.descricao, "acoes": sorted(it.acoes),
            "texto": it.texto, "campos": it.campos,
            **({"nota_explicativa_agu": " | ".join(it.notas)} if it.notas else {}),
            **({"alternativa": it.alternativa} if it.alternativa else {}),
        })
    dados_txt = json.dumps({k: v for k, v in dados.items() if v and k not in ("signatario", "cargo")}, ensure_ascii=False)
    return INSTRUCOES.format(tipo_nome=tipo_nome, versao=modelo.versao or "?", dados=dados_txt,
                             pendencias=json.dumps(catalogo, ensure_ascii=False, indent=1),
                             tr=texto_tr[:MAX_TR])


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

@dataclass
class ResultadoIA:
    decisoes: Decisoes = field(default_factory=Decisoes)
    aplicadas: list[dict] = field(default_factory=list)
    descartes: list[dict] = field(default_factory=list)
    sem_informacao: list[dict] = field(default_factory=list)


def _json(resposta: str) -> dict:
    texto = (resposta or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def evidencia_no_tr(evidencia: str, tr_normalizado: str) -> bool:
    e = _n(evidencia).strip(" .;:\"'“”…")
    if len(e) < 12:
        return False
    if e in tr_normalizado:
        return True
    # tolera diferença pequena (quebra de linha, hífen de PDF): melhor trecho com ≥ 90% de semelhança
    return fuzz.partial_ratio(e, tr_normalizado) >= 90


# Campo que pede número + extenso: "XX (valor por extenso)", "XX (xxxxx)", "XX (valor ou percentual por extenso)"
POR_EXTENSO = re.compile(r"\((?:valor[^)]*extenso|x{3,})\)", re.IGNORECASE)


def _tokens(texto: str) -> set[str]:
    """Números e palavras de 4+ letras: para conferir se a evidência fala do valor sugerido."""
    t = _n(texto)
    return set(re.findall(r"\d+(?:[.,]\d+)*", t)) | {w for w in re.findall(r"[a-z]{4,}", t)
                                                      if w not in _GENERICAS}


# Palavras que aparecem em qualquer TR/cláusula e não mostram que o trecho trata do assunto
_GENERICAS = {"para", "pelo", "pela", "como", "sendo", "serao", "sera", "sobre", "deste", "desta", "neste",
              "nesta", "conforme", "caso", "objeto", "contratacao", "empresa", "empresas", "servico", "servicos",
              "termo", "referencia", "administracao", "fornecedor", "fornecedores", "aviso", "dispensa",
              "licitacao", "item", "itens", "quando", "previsto", "prevista", "forma", "seus", "suas", "pela"}


def _trata_do_assunto(evidencia: str, texto_bloco: str) -> bool:
    return bool(_tokens(evidencia) & _tokens(texto_bloco))


def _opcao_valida(valor: str, opcoes: list[str]) -> bool:
    v = _n(valor)
    return any(v == _n(o) or v.startswith(_n(o) + " ") for o in opcoes)


def validar(itens: list[ItemPendente], resposta: str, texto_tr: str) -> ResultadoIA:
    r = ResultadoIA()
    try:
        dados = _json(resposta)
    except (json.JSONDecodeError, TypeError):
        r.descartes.append({"bloco": "", "motivo": "Resposta da IA não é um JSON válido"})
        return r

    por_bloco = {it.bloco: it for it in itens}
    alternativas = {it.alternativa["bloco"]: it for it in itens if it.alternativa}
    tr_n = _n(texto_tr)
    vistos: set[str] = set()

    def descarta(bloco: str, motivo: str) -> None:
        r.descartes.append({"bloco": bloco, "numero": por_bloco.get(bloco).numero if bloco in por_bloco else "", "motivo": motivo})

    for s in dados.get("decisoes") or []:
        if not isinstance(s, dict):
            continue
        bloco = str(s.get("bloco", "")).strip()
        acao = str(s.get("acao", "")).strip()
        motivo = str(s.get("motivo", "")).strip()
        evidencia = str(s.get("evidencia", "") or "").strip()
        it = por_bloco.get(bloco) or alternativas.get(bloco)
        if it is None:
            descarta(bloco, "Bloco não está entre as pendências enviadas")
            continue
        if bloco in vistos:
            descarta(bloco, "Mais de uma decisão para o mesmo bloco (mantida a primeira)")
            continue
        if acao not in it.acoes:
            descarta(bloco, f"Ação \"{acao}\" não se aplica a este tipo de pendência")
            continue
        if len(motivo) < MIN_MOTIVO:
            descarta(bloco, "Sem motivo")
            continue
        campos_s = s.get("campos") if isinstance(s.get("campos"), dict) else {}
        textos_modelo = {c["id"]: c["texto"] for c in it.campos}
        # Repetir o valor do próprio modelo ("Lei nº 14.133, de 2021") ou manter cláusula opcional
        # pelo estilo (redação padrão da AGU) não exige trecho do TR
        so_repete_modelo = acao == "preencher" and campos_s and all(
            _n(str(v)) == _n(textos_modelo.get(k, "")) for k, v in campos_s.items())
        exige = acao in EXIGE_EVIDENCIA and not so_repete_modelo and not (it.tipo == "opcional" and acao == "manter")
        if exige and not evidencia:
            descarta(bloco, "Sem trecho do TR que sustente a decisão")
            continue
        if evidencia and not evidencia_no_tr(evidencia, tr_n):
            descarta(bloco, "O trecho citado como evidência não foi encontrado no TR")
            continue

        # Remover, ou adotar cláusula opcional vermelha, só com trecho do TR que trate daquela cláusula:
        # o silêncio do TR não justifica tirar redação da AGU (a SELIT mantém OSCIP, lances automáticos...)
        texto_bloco = re.sub(r"⟦[^:]+: ", "", it.texto).replace("⟧", "")
        if it.alternativa:
            texto_bloco += " " + it.alternativa["texto"]
        if acao == "remover" or (acao == "manter" and it.tipo == "clausula"):
            if not evidencia or not _trata_do_assunto(evidencia, texto_bloco):
                descarta(bloco, "Sem trecho do TR que trate desta cláusula: fica para decisão do servidor")
                continue
        texto_motivo = motivo + (f" — TR: “{evidencia[:300]}”" if evidencia else "")
        d = r.decisoes
        if acao == "preencher":
            campos = s.get("campos") or {}
            validos = {c["id"]: c for c in it.campos if c["tipo"] in ("lacuna", "escolha")}
            aceitos, erro = {}, ""
            for cid, valor in campos.items() if isinstance(campos, dict) else []:
                valor = str(valor).strip()
                if cid not in validos:
                    erro = f"Campo {cid} não pertence ao bloco"
                elif not valor or COM_MARCADOR.search(valor) or MARCADOR_PRETO.search(valor):
                    erro = f"Valor do campo {cid} vazio ou com marcador do modelo"
                elif validos[cid]["opcoes"] and not _opcao_valida(valor, validos[cid]["opcoes"]):
                    erro = f"Valor do campo {cid} não é uma das opções do modelo"
                elif POR_EXTENSO.search(validos[cid]["texto"]) and not re.search(r"\d.*\(.+\)", valor):
                    erro = f"Valor do campo {cid} fora do padrão do modelo (número e extenso, ex.: “30 (trinta)”)"
                elif (evidencia and _n(valor) != _n(validos[cid]["texto"])
                        and not _tokens(valor) & _tokens(evidencia)):
                    erro = f"O trecho do TR citado não menciona o valor sugerido para {cid}"
                elif len(valor) > 1000:
                    erro = f"Valor do campo {cid} longo demais"
                else:
                    aceitos[cid] = valor
            if erro or not aceitos:
                descarta(bloco, erro or "Nenhum campo preenchido")
                continue
            for cid, valor in aceitos.items():
                d.campos[cid] = valor
                d.origem[cid] = "ia"
                d.motivos[cid] = texto_motivo
        elif acao in ("manter_trecho", "retirar_trecho"):
            cid = str(s.get("campo", "")).strip()
            if cid not in {c["id"] for c in it.campos if c["tipo"] == "trecho_opcional"}:
                descarta(bloco, "Campo de trecho opcional inválido")
                continue
            d.campos[cid] = MANTER_CAMPO if acao == "manter_trecho" else ""
            d.origem[cid] = "ia"
            d.motivos[cid] = texto_motivo
        elif acao == "manter":
            if it.alternativa:
                outro = it.alternativa["bloco"] if bloco == it.bloco else it.bloco
                d.remover[outro] = f"IA: escolhida a outra redação — {texto_motivo}"
                d.origem[outro] = "ia"
            else:
                d.manter.add(bloco)
                d.origem[bloco] = "ia"
                d.motivos[bloco] = texto_motivo
        elif acao == "remover":
            d.remover[bloco] = f"IA: {texto_motivo}"
            d.origem[bloco] = "ia"
        elif acao == "reescrever":
            novo = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", str(s.get("texto", "")).strip())   # sem numeração
            original = re.sub(r"⟦[^:]+: ", "", it.texto).replace("⟧", "")
            if not novo or MARCADOR_PRETO.search(novo) or "[" in novo:
                descarta(bloco, "Texto reescrito vazio ou ainda com marcador do modelo")
                continue
            if fuzz.token_set_ratio(_n(original), _n(novo)) < 50:
                descarta(bloco, "Texto reescrito muito diferente do modelo da AGU")
                continue
            if re.search(r"\bnao\b", _n(novo)) and not re.search(r"\bnao\b", _n(original)):
                descarta(bloco, "Para dizer que a cláusula não se aplica, a ação é remover, não reescrever")
                continue
            numeros = lambda x: set(re.findall(r"\d+(?:[.,]\d+)*", _n(x)))
            novos = numeros(novo) - numeros(original)
            if novos and not novos <= numeros(evidencia):
                descarta(bloco, f"O texto reescrito traz valores que não estão no trecho do TR citado ({', '.join(sorted(novos))})")
                continue
            d.textos[bloco] = novo
            d.origem[bloco] = "ia"
            d.motivos[bloco] = texto_motivo
        vistos.add(bloco)
        r.aplicadas.append({"bloco": bloco, "numero": it.numero, "acao": acao, "motivo": motivo, "evidencia": evidencia})

    for s in dados.get("sem_informacao") or []:
        if isinstance(s, dict) and str(s.get("bloco", "")) in por_bloco and s.get("bloco") not in vistos:
            r.sem_informacao.append({"bloco": s["bloco"], "numero": por_bloco[s["bloco"]].numero,
                                     "motivo": str(s.get("motivo", ""))[:400]})
    return r
