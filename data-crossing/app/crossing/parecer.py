"""
Parecer preliminar de IA sobre o cruzamento.

O parecer é opcional e apenas opinativo. O backend não tem internet:
ele monta o prompt, o navegador o envia ao Gemini (padrão de relé) e
devolve a resposta para validação aqui.

O parecer tem duas partes:

1. Avaliação geral — o modelo escolhe um nível numa escala fechada
   (NIVEIS_AVALIACAO). A frase que vai ao relatório é fixa, por nível;
   o modelo só escreve a fundamentação. Assim a conclusão nunca usa
   redação livre do modelo.
2. Itens — comentários pontuais, cada um citando o que o fundamenta.

Toda afirmação precisa citar referências existentes: IDs de achados
(A001...) ou IDs do catálogo de dados extraídos (E1, E1.P2...). O
catálogo permite opinar mesmo sem achados, sem perder rastreabilidade.

Regras de validação:
- referências citadas precisam existir;
- itens precisam citar ao menos uma referência;
- nível diferente de "sem_indicios" precisa citar ao menos uma referência;
- "sem_indicios" com achados de prioridade alta precisa citar todos eles
  (o modelo tem de justificar por que os descarta);
- linguagem conclusiva é proibida — inclusive a negativa ("não houve
  conluio"): afirmar ausência também é concluir.

Itens reprovados não são corrigidos: são descartados e listados no
relatório com o motivo, para que o descarte também seja auditável.
"""

import json
import re
from datetime import datetime
from typing import Any

from app.crossing.rules import Empresa, filtrar_ignorados

MAX_ITENS = 30
MAX_CARACTERES_ITEM = 1500
MAX_CARACTERES_FUNDAMENTACAO = 2500

# Escala fechada. O texto é o que aparece no relatório.
NIVEIS_AVALIACAO: dict[str, str] = {
    "sem_indicios": (
        "Na avaliação preliminar do modelo, os dados analisados não apresentam "
        "indícios de conluio entre as licitantes."
    ),
    "coincidencias_a_verificar": (
        "Na avaliação preliminar do modelo, há coincidências que recomendam verificação, "
        "sem que configurem, por si sós, indício relevante de conluio."
    ),
    "indicios_relevantes": (
        "Na avaliação preliminar do modelo, há indícios de possível conluio que "
        "recomendam diligência prioritária."
    ),
}

RESSALVA_AVALIACAO = (
    "Avaliação restrita aos dados extraídos dos documentos apresentados. A ausência de "
    "indícios nesses dados não exclui a existência de vínculos não documentados, e a "
    "presença de coincidências não implica irregularidade. A decisão cabe ao servidor competente."
)

_REFERENCIA = re.compile(r"\b(A\d{3}|E\d+(?:\.[PJTCL]\d+)?)\b")

# (padrão, motivo legível). A lista é deliberadamente rígida: um item
# válido descartado por engano custa menos que uma afirmação conclusiva
# anexada ao processo.
_PADROES_CONCLUSIVOS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), motivo)
    for p, motivo in [
        (r"\bhouve\s+(conluio|fraude|combina[çc][ãa]o|cartel|conchavo|ajuste)", "afirma a ocorrência ou a ausência do fato"),
        (r"\b(n[ãa]o\s+(h[áa]|existe|existiu|ocorreu)|inexiste|inexistiu|aus[êe]ncia\s+de)\s+(conluio|fraude|combina[çc][ãa]o|cartel)", "afirma a ausência do fato"),
        (r"\bfraud\w*", "menciona fraude"),
        (r"\b(cartel|cartelizad\w*|conluiad\w*)\b", "qualifica as empresas"),
        (r"\bconluio\s+(comprovado|confirmado|evidente|caracterizado|configurado|claro|manifesto|patente|descartado|afastado|exclu[íi]do)", "qualifica o conluio como certo ou descartado"),
        (r"\b(ficou|fica|est[áa]|resta|restou|foi|foram)\s+(comprovad|demonstrad|caracterizad|configurad|evidenciad|provad|descartad|afastad)\w*", "afirma comprovação ou descarte"),
        (r"\bcomprova(m|do|da|dos|das|ndo|r)?\b", "afirma comprovação"),
        (r"\b(confirma|constata|atesta|prova)(m|do|da)?\s+(o\s+|a\s+)?(conluio|fraude|irregularidade|combina[çc][ãa]o)", "afirma comprovação"),
        (r"\b(certamente|inequivocamente|indubitavelmente|incontestavelmente|inquestionavelmente|seguramente)\b", "usa termo de certeza"),
        (r"\bsem\s+(sombra\s+de\s+)?d[úu]vida", "usa termo de certeza"),
        (r"\b(culpad\w*|crime|criminos\w*|il[íi]cit\w*|delito|idône\w*|inidône\w*)\b", "atribui responsabilidade ou idoneidade"),
        (r"\b(as|estas|essas|tais|ambas\s+as)\s+empresas\s+(s[ãa]o|est[ãa]o|agiram|atuaram)\s+(em\s+)?(conluio|combinad|conluiad|associad)\w*", "afirma conduta das empresas"),
        (r"\b(a\s+)?(ia|intelig[êe]ncia\s+artificial)\s+(identificou|concluiu|constatou|detectou)", "atribui conclusão à IA"),
    ]
]


# ---------------------------------------------------------------------------
# Catálogo de dados extraídos
# ---------------------------------------------------------------------------

def montar_catalogo(sessao: dict) -> dict[str, str]:
    """
    Numera os dados extraídos para que o parecer possa citá-los.

    E1           → empresa 1 (razão social e CNPJ)
    E1.P2        → pessoa 2 da empresa 1 (nome, função, cônjuge, filiação)
    E1.J1        → CNPJ de terceiro nos documentos da empresa 1
    E1.T1, E1.C1 → telefone e CEP
    E1.L1        → endereço da empresa (sede, filial...)

    CPFs não entram: coincidências de CPF já estão nos achados (R02), e
    não é preciso expor o número para o modelo opinar. Os dados excluídos
    do cruzamento (consultante SICAF, órgãos de registro) também não entram,
    para que o modelo não os aponte como vínculo.

    A numeração de pessoas segue a ordem da seção 1 do relatório, que lista
    as pessoas sem filtro; por isso o índice é o da lista original.
    """
    catalogo: dict[str, str] = {}
    for i, emp in enumerate(sessao.get("empresas", []), 1):
        filtrada, _ = filtrar_ignorados(Empresa(
            id=emp["id"], nome=emp["nome"], cnpj_principal=emp["cnpj_principal"],
            cnpjs=emp["cnpjs"], cpfs=emp["cpfs"], ceps=emp["ceps"],
            telefones=emp["telefones"], pessoas=emp["pessoas"],
            enderecos=emp.get("enderecos", []),
        ))
        pessoas_mantidas = {id(p) for p in filtrada.pessoas}
        cnpjs_mantidos = {c["valor"] for c in filtrada.cnpjs}

        catalogo[f"E{i}"] = f"Empresa licitante: {emp['nome']} (CNPJ {emp.get('cnpj_principal')})"
        for j, p in enumerate(emp.get("pessoas", []), 1):
            if id(p) not in pessoas_mantidas:
                continue
            partes = [p.get("nome") or "?", f"função: {p.get('funcao') or 'não identificada'}"]
            for chave, rotulo in (("conjuge", "cônjuge"), ("filiacao_pai", "pai"),
                                  ("filiacao_mae", "mãe"), ("endereco", "endereço")):
                if p.get(chave):
                    partes.append(f"{rotulo}: {p[chave]}")
            catalogo[f"E{i}.P{j}"] = "; ".join(partes)
        terceiros = [
            c for c in emp.get("cnpjs", [])
            if c["valor"] != emp.get("cnpj_principal") and c["valor"] in cnpjs_mantidos
        ]
        for j, c in enumerate(terceiros, 1):
            catalogo[f"E{i}.J{j}"] = f"CNPJ citado nos documentos: {c['valor_formatado']} — {(c.get('trecho') or '')[:120]}"
        for j, t in enumerate(emp.get("telefones", []), 1):
            catalogo[f"E{i}.T{j}"] = f"Telefone: {t['valor_formatado']}"
        for j, c in enumerate(emp.get("ceps", []), 1):
            catalogo[f"E{i}.C{j}"] = f"CEP: {c['valor_formatado']}"
        for j, end in enumerate(emp.get("enderecos", []), 1):
            catalogo[f"E{i}.L{j}"] = f"Endereço: {end['valor']} ({end.get('trecho') or 'empresa'})"
    return catalogo


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def montar_prompt(processo_id: str, achados: list[dict], catalogo: dict[str, str]) -> str:
    """Monta o prompt enviado ao Gemini pelo navegador."""
    resumo_achados = [
        {
            "id": a["id"],
            "prioridade": a.get("prioridade"),
            "regra": a["regra_codigo"],
            "descricao": a["regra_descricao"],
            "empresa_a": a["empresa_a"],
            "empresa_b": a["empresa_b"],
            "campo": a["campo"],
            "valor": a["valor"],
            "trecho_a": (a.get("evidencia_a") or {}).get("trecho", "")[:200],
            "trecho_b": (a.get("evidencia_b") or {}).get("trecho", "")[:200],
        }
        for a in achados
    ]
    return f"""Você auxilia um servidor público da Justiça Federal na análise de possível conluio entre empresas licitantes (processo {processo_id}).

Abaixo estão (1) os ACHADOS: coincidências objetivas encontradas por regras determinísticas entre as empresas; e (2) o CATÁLOGO: os dados extraídos dos documentos de cada empresa, numerados.

Sua tarefa é dar uma opinião PRELIMINAR, IMPARCIAL e NÃO CONCLUSIVA. Considere tanto o que aponta para vínculo entre as empresas quanto o que aponta em sentido contrário (ex.: coincidência explicável por cartório, junta comercial, contador ou grupo familiar interno de uma mesma empresa). Não confirme automaticamente os achados: avalie-os.

PARTE 1 — AVALIAÇÃO GERAL. Escolha exatamente um nível:
- "sem_indicios": os dados não apresentam indícios de conluio entre as licitantes;
- "coincidencias_a_verificar": há coincidências que merecem verificação, mas não configuram por si sós indício relevante;
- "indicios_relevantes": há indícios de possível conluio que recomendam diligência prioritária.
Na "fundamentacao", explique o nível citando IDs (ex.: A001, E2.P1). Se escolher "sem_indicios" e houver achados de prioridade alta, cite cada um e explique por que não os considera indício.

PARTE 2 — ITENS. Comentários pontuais, cada um citando os IDs em que se baseia e sugerindo uma diligência objetiva. Pode ser vazia.

REGRAS OBRIGATÓRIAS:
1. Cite somente IDs que existem abaixo.
2. Não afirme que houve ou que não houve conluio, fraude ou combinação. Não use "comprovado", "descartado", "certamente" ou termos equivalentes. Use "indício", "coincidência", "não foram identificados indícios nos dados analisados", "recomenda-se diligência".
3. Considere apenas relações ENTRE empresas licitantes diferentes. Vínculos internos de uma mesma empresa (sócios da mesma família, holding própria) não são indício de conluio entre licitantes.
4. Itens que descumprirem estas regras serão descartados automaticamente.

Responda APENAS com JSON válido, sem markdown, no formato:
{{"avaliacao_geral": {{"nivel": "sem_indicios", "fundamentacao": "...", "referencias": ["E1", "A001"]}},
 "itens": [{{"texto": "...", "referencias": ["A001"]}}]}}

ACHADOS ({len(resumo_achados)}):
{json.dumps(resumo_achados, ensure_ascii=False, indent=1)}

CATÁLOGO:
{json.dumps(catalogo, ensure_ascii=False, indent=1)}
"""


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def _extrair_json(resposta: Any) -> dict:
    """Aceita o objeto já parseado ou o texto bruto devolvido pelo modelo."""
    if isinstance(resposta, dict):
        return resposta
    if not isinstance(resposta, str):
        raise ValueError("resposta em formato desconhecido")

    texto = resposta.strip()
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise ValueError("resposta não contém JSON")
    return json.loads(texto[inicio:fim + 1])


def linguagem_conclusiva(texto: str) -> str | None:
    """Retorna o motivo e o trecho, se o texto usar linguagem conclusiva."""
    for padrao, motivo in _PADROES_CONCLUSIVOS:
        m = padrao.search(texto)
        if m:
            return f"linguagem conclusiva ({motivo}): “{m.group(0)}”"
    return None


def _referencias(item: dict, texto: str) -> list[str]:
    """Junta as referências declaradas e as mencionadas no texto."""
    citadas = item.get("referencias")
    if citadas is None:
        citadas = item.get("achados") or []   # formato anterior
    if not isinstance(citadas, list):
        citadas = [citadas]
    citadas = [str(c).strip().upper() for c in citadas if str(c).strip()]
    return list(dict.fromkeys(citadas + _REFERENCIA.findall(texto.upper())))


def _validar_avaliacao(bruta: Any, validos: set[str], ids_alta: set[str]) -> tuple[dict | None, dict | None]:
    """Retorna (avaliação aceita, descarte) — exatamente um dos dois."""
    if not isinstance(bruta, dict):
        return None, {"texto": str(bruta)[:300], "achados": [], "motivo": "avaliação geral ausente ou em formato inválido"}

    nivel = str(bruta.get("nivel") or "").strip().lower()
    texto = " ".join(str(bruta.get("fundamentacao") or "").split())
    citadas = _referencias(bruta, texto)
    registro = {"texto": f"[avaliação geral: {nivel or '—'}] {texto}", "achados": citadas}

    if nivel not in NIVEIS_AVALIACAO:
        motivo = f"nível de avaliação fora da escala: “{nivel}”"
    elif not texto:
        motivo = "avaliação geral sem fundamentação"
    elif len(texto) > MAX_CARACTERES_FUNDAMENTACAO:
        motivo = f"fundamentação excede {MAX_CARACTERES_FUNDAMENTACAO} caracteres"
    elif inexistentes := [c for c in citadas if c not in validos]:
        motivo = f"cita referência inexistente: {', '.join(inexistentes)}"
    elif nivel != "sem_indicios" and not citadas:
        motivo = "nível com indícios sem citar achados ou dados"
    elif nivel == "sem_indicios" and (faltantes := sorted(ids_alta - set(citadas))):
        motivo = f"“sem indícios” sem examinar achado(s) de prioridade alta: {', '.join(faltantes)}"
    else:
        motivo = linguagem_conclusiva(texto)

    if motivo:
        return None, {**registro, "motivo": motivo}
    return {
        "nivel": nivel,
        "conclusao": NIVEIS_AVALIACAO[nivel],
        "fundamentacao": texto,
        "referencias": citadas,
        "ressalva": RESSALVA_AVALIACAO,
    }, None


def validar_parecer(
    resposta: Any,
    ids_validos: set[str],
    modelo: str = "",
    ids_alta: set[str] | None = None,
) -> dict:
    """
    Valida a resposta do modelo.

    Args:
        ids_validos: IDs de achados e do catálogo que podem ser citados
        ids_alta: IDs dos achados de prioridade alta

    Returns:
        {"modelo", "gerado_em", "avaliacao_geral": dict|None, "aceitos": [...], "descartados": [...]}
    """
    parecer = {
        "modelo": modelo,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "avaliacao_geral": None,
        "aceitos": [],
        "descartados": [],
    }

    try:
        dados = _extrair_json(resposta)
        if not isinstance(dados, dict):
            raise ValueError("JSON não é um objeto")
        itens = dados.get("itens") or []
        if not isinstance(itens, list):
            raise ValueError('campo "itens" não é lista')
    except (ValueError, json.JSONDecodeError) as e:
        parecer["descartados"].append({
            "texto": str(resposta)[:300],
            "achados": [],
            "motivo": f"resposta inválida: {e}",
        })
        return parecer

    if "avaliacao_geral" in dados:
        aceita, descarte = _validar_avaliacao(dados["avaliacao_geral"], ids_validos, ids_alta or set())
        parecer["avaliacao_geral"] = aceita
        if descarte:
            parecer["descartados"].append(descarte)

    for i, item in enumerate(itens):
        if not isinstance(item, dict):
            item = {"texto": str(item)}

        texto = " ".join(str(item.get("texto") or "").split())
        citados = _referencias(item, texto)
        registro = {"texto": texto, "achados": citados}

        if i >= MAX_ITENS:
            motivo = f"excede o limite de {MAX_ITENS} itens"
        elif not texto:
            motivo = "item sem texto"
        elif len(texto) > MAX_CARACTERES_ITEM:
            motivo = f"texto excede {MAX_CARACTERES_ITEM} caracteres"
        elif not citados:
            motivo = "não cita nenhum achado ou dado"
        elif inexistentes := [c for c in citados if c not in ids_validos]:
            motivo = f"cita referência inexistente: {', '.join(inexistentes)}"
        else:
            motivo = linguagem_conclusiva(texto)

        if motivo:
            parecer["descartados"].append({**registro, "motivo": motivo})
        else:
            parecer["aceitos"].append(registro)

    return parecer
