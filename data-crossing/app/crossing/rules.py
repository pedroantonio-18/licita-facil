"""
Regras de cruzamento entre empresas participantes de licitação.

Cada regra é identificada por um código único, tem critério
objetivo e documentado, e retorna achados com rastreabilidade
completa de origem.

IMPORTANTE: Este módulo apenas aponta coincidências e sobreposições
de dados. Nenhuma conclusão jurídica é emitida aqui.
A interpretação dos achados é responsabilidade do servidor competente.
"""

import os
import re
import unicodedata
from dataclasses import dataclass, field, replace
from itertools import combinations

from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
# Valores excluídos do cruzamento
# ---------------------------------------------------------------------------
#
# Alguns números aparecem nos documentos de várias empresas sem qualquer
# relação com elas. Cruzá-los geraria achados falsos. Cada exclusão tem
# motivo documentado e é listada no relatório (seção "Dados desconsiderados"),
# para que o servidor possa conferir.
#
# Valores adicionais podem ser informados por variável de ambiente,
# separados por vírgula: CPF_IGNORADOS e CNPJ_IGNORADOS.

# CPF do "usuário consultante" que aparece no cabeçalho de toda consulta SICAF
# ("NOME 000.000.000-00 - Governo (Uasg: 90022)"). É o servidor que emitiu a
# consulta, não pessoa vinculada à licitante.
#
# O CPF é dado pessoal e NÃO fica no código: configure-o no servidor em
# CPF_IGNORADOS (separados por vírgula, se houver mais de um consultante).
# Independentemente disso, a extração local descarta o CPF do cabeçalho SICAF
# e filtrar_ignorados() descarta o CPF de quem tem função de consultante.
_CPF_IGNORADOS: dict[str, str] = {}
_MOTIVO_CPF_CONSULTANTE = "Usuário consultante no cabeçalho das consultas SICAF"

# CNPJs de órgãos de registro e certificação que aparecem em carimbos,
# rodapés e páginas de validação de assinatura eletrônica.
_CNPJS_INSTITUCIONAIS: dict[str, str] = {
    "02088698000174": "Junta Comercial do Estado de Goiás (JUCEG) — validação de assinatura eletrônica",
}


# Pessoas que assinam ou certificam documentos de várias empresas sem ter
# vínculo com elas: a Secretária-Geral da Junta Comercial assina o registro
# de todas as empresas do estado; escreventes e tabeliães lavram procurações
# de quem for ao cartório. Comparadas pela função extraída (sem acentos).
# Advogados e testemunhas NÃO entram: o mesmo advogado em duas licitantes é
# coincidência relevante.
_FUNCOES_INSTITUCIONAIS = re.compile(
    r"secretari[oa][\s-]*geral|junta comercial|\bjuc[a-z]{1,4}\b|escrevente|tabeli|"
    r"oficial\s+(registrador|de\s+registro|do\s+cartorio)|registrador|notari|cartorio|"
    r"juiz[a]?\s+de\s+paz|examinador|\bvogal\b|autenticador|consultante"
)


def _carregar_env(nome: str, motivo: str) -> dict[str, str]:
    valores = os.environ.get(nome, "")
    return {
        re.sub(r"\D", "", v): motivo
        for v in valores.split(",")
        if re.sub(r"\D", "", v)
    }


def cpfs_ignorados() -> dict[str, str]:
    return {**_CPF_IGNORADOS, **_carregar_env("CPF_IGNORADOS", _MOTIVO_CPF_CONSULTANTE)}


def cnpjs_ignorados() -> dict[str, str]:
    return {**_CNPJS_INSTITUCIONAIS, **_carregar_env("CNPJ_IGNORADOS", "Configurado em CNPJ_IGNORADOS")}


# ---------------------------------------------------------------------------
# Prioridade de triagem
# ---------------------------------------------------------------------------
#
# A prioridade só ordena a leitura do servidor; não é juízo de valor.
# Critério: quanto mais o dado identifica uma pessoa ou vínculo específico,
# maior a prioridade de verificação.

PRIORIDADE_POR_REGRA: dict[str, str] = {
    "R06": "alta",    # mesma pessoa na mesma função
    "R02": "alta",    # mesmo CPF
    "R01": "media",   # mesmo CNPJ de terceiro
    "R03": "media",   # mesmo telefone
    "R07": "alta",    # vínculo familiar (cônjuge, pai/mãe, irmãos) entre empresas
    "R01": "media",   # mesmo CNPJ de terceiro
    "R03": "media",   # mesmo telefone
    "R05": "media",   # nome similar
    "R08": "media",   # mesmo endereço (pode ser edifício comercial ou contador)
    "R04": "baixa",   # mesmo CEP (comum em edifícios comerciais)
}

ORDEM_PRIORIDADE = {"alta": 0, "media": 1, "baixa": 2}


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class Empresa:
    """
    Representa uma empresa com seus dados extraídos e normalizados.

    Os valores nos campos são os normalizados (sem formatação),
    mas cada campo guarda também sua origem para rastreabilidade.
    """
    id: str                          # identificador único no banco
    nome: str                        # razão social
    cnpj_principal: str              # CNPJ da empresa licitante (14 dígitos)
    cnpjs: list[dict]                # todos os CNPJs extraídos
    cpfs: list[dict]                 # todos os CPFs extraídos
    ceps: list[dict]                 # todos os CEPs extraídos
    telefones: list[dict]            # todos os telefones extraídos
    pessoas: list[dict]              # pessoas com funções
    enderecos: list[dict] = field(default_factory=list)  # endereços da empresa (sede, filiais...)


@dataclass
class Achado:
    """
    Representa uma coincidência encontrada entre duas empresas.

    Cada achado é rastreável: informa qual regra gerou o achado,
    quais empresas estão envolvidas, qual campo coincide e onde
    cada dado foi encontrado nos documentos originais.
    """
    regra_codigo: str        # ex: "R01"
    regra_descricao: str     # descrição legível da regra
    empresa_a_id: str
    empresa_a_nome: str
    empresa_b_id: str
    empresa_b_nome: str
    campo: str               # ex: "cpf", "telefone", "cep"
    valor: str               # valor que coincide (formatado)
    similaridade: float      # 1.0 = identidade exata
    evidencia_a: dict        # origem do dado na empresa A (pagina, trecho)
    evidencia_b: dict        # origem do dado na empresa B (pagina, trecho)
    nota: str = ""           # observação adicional para o servidor
    id: str = ""             # ex: "A001" — atribuído após a ordenação; citado pelo parecer
    prioridade: str = ""     # alta | media | baixa — ver PRIORIDADE_POR_REGRA


# ---------------------------------------------------------------------------
# Motor de cruzamento
# ---------------------------------------------------------------------------

def filtrar_ignorados(empresa: Empresa) -> tuple[Empresa, list[dict]]:
    """
    Remove da empresa os CPFs e CNPJs que não devem ser cruzados.

    Pessoas cujo CPF está ignorado (ex.: consultante SICAF) também são
    removidas, inclusive quando aparecem sem CPF mas com o mesmo nome.

    Returns:
        (empresa filtrada, lista de itens desconsiderados com motivo)
    """
    ign_cpf = cpfs_ignorados()
    ign_cnpj = cnpjs_ignorados()
    desconsiderados: list[dict] = []

    # CPF de quem tem função de consultante, Junta ou cartório também não é
    # cruzado — sem depender de configuração (ex.: consultante SICAF).
    for p in empresa.pessoas:
        cpf = re.sub(r"\D", "", p.get("cpf") or "")
        funcao = _sem_acentos((p.get("funcao") or "").lower())
        if cpf and cpf not in ign_cpf and _FUNCOES_INSTITUCIONAIS.search(funcao):
            ign_cpf = {**ign_cpf, cpf: f"CPF de agente de registro, cartório ou consulta (função: {p.get('funcao')})"}

    def _registro(tipo, campo, motivo):
        return {
            "empresa": empresa.nome,
            "tipo": tipo,
            "valor": campo.get("valor_formatado") or campo.get("valor") or campo.get("nome"),
            "motivo": motivo,
        }

    cpfs = []
    nomes_ignorados = set()
    for c in empresa.cpfs:
        if c["valor"] in ign_cpf:
            desconsiderados.append(_registro("cpf", c, ign_cpf[c["valor"]]))
        else:
            cpfs.append(c)

    cnpjs = []
    for c in empresa.cnpjs:
        if c["valor"] in ign_cnpj and c["valor"] != empresa.cnpj_principal:
            desconsiderados.append(_registro("cnpj", c, ign_cnpj[c["valor"]]))
        else:
            cnpjs.append(c)

    pessoas_com_cpf_ignorado = [
        p for p in empresa.pessoas
        if re.sub(r"\D", "", p.get("cpf") or "") in ign_cpf
    ]
    for p in pessoas_com_cpf_ignorado:
        nomes_ignorados.add(_nome_chave(p["nome"]))

    pessoas = []
    for p in empresa.pessoas:
        cpf = re.sub(r"\D", "", p.get("cpf") or "")
        funcao = _sem_acentos((p.get("funcao") or "").lower())
        if cpf in ign_cpf:
            desconsiderados.append(_registro("pessoa", p, ign_cpf[cpf]))
        elif _nome_chave(p["nome"]) in nomes_ignorados:
            desconsiderados.append(_registro("pessoa", p, "Mesmo nome de pessoa com CPF desconsiderado"))
        elif _FUNCOES_INSTITUCIONAIS.search(funcao):
            desconsiderados.append(_registro(
                "pessoa", p,
                f"Agente de órgão de registro, cartório ou consulta (função: {p.get('funcao')})",
            ))
        else:
            pessoas.append(p)

    filtrada = replace(empresa, cpfs=cpfs, cnpjs=cnpjs, pessoas=pessoas)
    return filtrada, desconsiderados


def _nome_chave(nome: str) -> str:
    return " ".join((nome or "").upper().split())


def cruzar_empresas(empresas: list[Empresa]) -> list[Achado]:
    """
    Executa todas as regras de cruzamento para cada par de empresas.

    A entrada já deve estar filtrada por filtrar_ignorados().

    Args:
        empresas: lista de empresas a cruzar

    Returns:
        Lista de achados ordenada por regra, com id sequencial (A001, A002...)
        e prioridade de triagem preenchidos.
    """
    achados: list[Achado] = []

    # Gera todos os pares únicos sem repetição
    for empresa_a, empresa_b in combinations(empresas, 2):
        achados.extend(_aplicar_todas_regras(empresa_a, empresa_b))

    # Ordena de forma determinística para que os ids sejam estáveis
    achados.sort(key=lambda a: (a.regra_codigo, a.empresa_a_nome, a.empresa_b_nome, a.campo, a.valor))

    for i, achado in enumerate(achados, 1):
        achado.id = f"A{i:03d}"
        achado.prioridade = PRIORIDADE_POR_REGRA.get(achado.regra_codigo, "baixa")

    return achados


# ---------------------------------------------------------------------------
# Aplicação das regras
# ---------------------------------------------------------------------------

def _aplicar_todas_regras(a: Empresa, b: Empresa) -> list[Achado]:
    achados = []
    achados.extend(_r01_cnpj_compartilhado(a, b))
    achados.extend(_r02_cpf_compartilhado(a, b))
    achados.extend(_r03_telefone_identico(a, b))
    achados.extend(_r04_cep_identico(a, b))
    achados.extend(_r05_pessoa_em_comum(a, b))
    achados.extend(_r06_funcao_em_comum(a, b))
    achados.extend(_r07_vinculo_familiar(a, b))
    achados.extend(_r08_endereco_coincidente(a, b))
    return achados


def _r01_cnpj_compartilhado(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R01 — CNPJ presente nos documentos de duas empresas distintas.

    Critério: mesmo CNPJ normalizado (14 dígitos) aparece nos documentos
    de ambas as empresas, exceto os próprios CNPJs principais de cada uma.
    Pode indicar sócio pessoa jurídica em comum, contador, ou cartório compartilhado.
    """
    achados = []
    cnpjs_a = {c["valor"] for c in a.cnpjs if c["valor"] != a.cnpj_principal}
    cnpjs_b = {c["valor"] for c in b.cnpjs if c["valor"] != b.cnpj_principal}
    comuns = cnpjs_a & cnpjs_b

    for cnpj in comuns:
        ev_a = next(c for c in a.cnpjs if c["valor"] == cnpj)
        ev_b = next(c for c in b.cnpjs if c["valor"] == cnpj)
        achados.append(Achado(
            regra_codigo="R01",
            regra_descricao="CNPJ presente nos documentos de ambas as empresas",
            empresa_a_id=a.id, empresa_a_nome=a.nome,
            empresa_b_id=b.id, empresa_b_nome=b.nome,
            campo="cnpj",
            valor=ev_a["valor_formatado"],
            similaridade=1.0,
            evidencia_a={"pagina": ev_a["pagina"], "trecho": ev_a["trecho"]},
            evidencia_b={"pagina": ev_b["pagina"], "trecho": ev_b["trecho"]},
            nota="O achado deve ser submetido à análise do servidor responsável para verificação do contexto em que o CNPJ aparece.",
        ))
    return achados


def _r02_cpf_compartilhado(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R02 — CPF presente nos documentos de duas empresas distintas.

    Critério: mesmo CPF normalizado (11 dígitos) extraído de documentos
    de ambas as empresas. Pode indicar sócio, administrador, procurador,
    contador ou advogado em comum.
    """
    achados = []
    cpfs_a = {c["valor"]: c for c in a.cpfs}
    cpfs_b = {c["valor"]: c for c in b.cpfs}
    comuns = set(cpfs_a) & set(cpfs_b)

    for cpf in comuns:
        ev_a = cpfs_a[cpf]
        ev_b = cpfs_b[cpf]
        achados.append(Achado(
            regra_codigo="R02",
            regra_descricao="O mesmo CPF consta em documentos de empresas distintas",
            empresa_a_id=a.id, empresa_a_nome=a.nome,
            empresa_b_id=b.id, empresa_b_nome=b.nome,
            campo="cpf",
            valor=ev_a["valor_formatado"],
            similaridade=1.0,
            evidencia_a={"pagina": ev_a["pagina"], "trecho": ev_a["trecho"]},
            evidencia_b={"pagina": ev_b["pagina"], "trecho": ev_b["trecho"]},
            nota="O achado deve ser submetido à análise do servidor responsável.",
        ))
    return achados


def _r03_telefone_identico(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R03 — Mesmo telefone (DDD + número) em documentos de empresas distintas.

    Critério: identidade exata após normalização (apenas dígitos).
    """
    achados = []
    tel_a = {t["valor"]: t for t in a.telefones}
    tel_b = {t["valor"]: t for t in b.telefones}
    comuns = set(tel_a) & set(tel_b)

    for tel in comuns:
        ev_a = tel_a[tel]
        ev_b = tel_b[tel]
        achados.append(Achado(
            regra_codigo="R03",
            regra_descricao="O mesmo número de telefone foi extraído de documentos de empresas distintas",
            empresa_a_id=a.id, empresa_a_nome=a.nome,
            empresa_b_id=b.id, empresa_b_nome=b.nome,
            campo="telefone",
            valor=ev_a["valor_formatado"],
            similaridade=1.0,
            evidencia_a={"pagina": ev_a["pagina"], "trecho": ev_a["trecho"]},
            evidencia_b={"pagina": ev_b["pagina"], "trecho": ev_b["trecho"]},
            nota="O achado deve ser submetido à análise do servidor responsável.",
        ))
    return achados


def _r04_cep_identico(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R04 — Mesmo CEP em documentos de empresas distintas.

    Critério: identidade exata de 8 dígitos normalizados.
    Nota: CEP idêntico pode ser coincidência em grandes edifícios comerciais.
    O servidor deve avaliar o contexto do endereço completo.
    """
    achados = []
    cep_a = {c["valor"]: c for c in a.ceps}
    cep_b = {c["valor"]: c for c in b.ceps}
    comuns = set(cep_a) & set(cep_b)

    for cep in comuns:
        ev_a = cep_a[cep]
        ev_b = cep_b[cep]
        achados.append(Achado(
            regra_codigo="R04",
            regra_descricao="O mesmo CEP foi extraído de documentos de empresas distintas",
            empresa_a_id=a.id, empresa_a_nome=a.nome,
            empresa_b_id=b.id, empresa_b_nome=b.nome,
            campo="cep",
            valor=ev_a["valor_formatado"],
            similaridade=1.0,
            evidencia_a={"pagina": ev_a["pagina"], "trecho": ev_a["trecho"]},
            evidencia_b={"pagina": ev_b["pagina"], "trecho": ev_b["trecho"]},
            nota="CEP idêntico pode ocorrer em edifícios comerciais com múltiplos ocupantes. O servidor deve avaliar o endereço completo.",
        ))
    return achados


def _r05_pessoa_em_comum(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R05 — Nome de pessoa física similar em documentos de empresas distintas.

    Critério: similaridade ≥ 92% pelo algoritmo token_sort_ratio (rapidfuzz),
    que é robusto a variações de ordem das palavras e erros de OCR.
    O limiar de 92% foi escolhido para capturar variações como
    "João da Silva" vs "João Silva" enquanto evita falsos positivos.
    """
    LIMIAR = 92.0
    achados = []

    for pa in a.pessoas:
        for pb in b.pessoas:
            score = fuzz.token_sort_ratio(
                pa["nome"].upper(),
                pb["nome"].upper()
            )
            if score >= LIMIAR:
                achados.append(Achado(
                    regra_codigo="R05",
                    regra_descricao="Nome de pessoa física similar localizado em documentos de empresas distintas",
                    empresa_a_id=a.id, empresa_a_nome=a.nome,
                    empresa_b_id=b.id, empresa_b_nome=b.nome,
                    campo="nome_pessoa",
                    valor=f"{pa['nome']} / {pb['nome']}",
                    similaridade=round(score / 100, 3),
                    evidencia_a={"pagina": pa.get("pagina", 0), "trecho": pa.get("trecho", ""), "funcao": pa.get("funcao")},
                    evidencia_b={"pagina": pb.get("pagina", 0), "trecho": pb.get("trecho", ""), "funcao": pb.get("funcao")},
                    nota=f"Similaridade de {score:.0f}%. O achado deve ser submetido à análise do servidor responsável.",
                ))
    return achados


def _r06_funcao_em_comum(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R06 — Mesma pessoa em mesma função em duas empresas distintas.

    Critério: nome similar (≥ 92%) E mesma função (ex: procurador em ambas).
    Achado mais específico que R05 — indica vínculo funcional idêntico.
    """
    LIMIAR = 92.0
    achados = []

    for pa in a.pessoas:
        for pb in b.pessoas:
            funcao_a = (pa.get("funcao") or "").strip().lower()
            funcao_b = (pb.get("funcao") or "").strip().lower()
            if not funcao_a or funcao_a == "não identificada" or funcao_a != funcao_b:
                continue
            score = fuzz.token_sort_ratio(
                pa["nome"].upper(),
                pb["nome"].upper()
            )
            if score >= LIMIAR:
                achados.append(Achado(
                    regra_codigo="R06",
                    regra_descricao=f"A mesma pessoa exerce a função '{pa['funcao']}' em empresas distintas",
                    empresa_a_id=a.id, empresa_a_nome=a.nome,
                    empresa_b_id=b.id, empresa_b_nome=b.nome,
                    campo="funcao_pessoa",
                    valor=f"{pa['nome']} ({pa['funcao']})",
                    similaridade=round(score / 100, 3),
                    evidencia_a={"pagina": pa.get("pagina", 0), "trecho": pa.get("trecho", ""), "funcao": pa.get("funcao")},
                    evidencia_b={"pagina": pb.get("pagina", 0), "trecho": pb.get("trecho", ""), "funcao": pb.get("funcao")},
                    nota=f"Similaridade de {score:.0f}%. O achado deve ser submetido à análise do servidor responsável.",
                ))
    return achados


# ---------------------------------------------------------------------------
# Comparação de nomes em campos relacionais (cônjuge, filiação)
# ---------------------------------------------------------------------------

_PARTICULAS = {"DA", "DE", "DO", "DAS", "DOS", "E", "D"}


def _sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _tokens_nome(nome: str) -> list[str]:
    limpo = re.sub(r"[^A-Z ]", " ", _sem_acentos((nome or "").upper()))
    return [t for t in limpo.split() if t not in _PARTICULAS]


def _nomes_equivalentes(x: str | None, y: str | None) -> tuple[bool, float]:
    """
    Decide se dois nomes designam a mesma pessoa.

    - Similaridade ≥ 92% (token_sort_ratio), como na R05; ou
    - mesmo prenome e todos os nomes do mais curto contidos no mais longo,
      com ao menos 3 nomes (sem partículas). Cobre o sobrenome de casada:
      "Ana Paula Moreira Lima" × "Ana Paula Moreira Lima Duarte". O mínimo
      de 3 nomes evita "José Silva" casar com qualquer "José ... Silva".
    """
    ta, tb = _tokens_nome(x or ""), _tokens_nome(y or "")
    if len(ta) < 2 or len(tb) < 2:
        return False, 0.0
    score = fuzz.token_sort_ratio(" ".join(ta), " ".join(tb))
    if score >= 92:
        return True, score
    menor, maior = sorted((ta, tb), key=len)
    if len(menor) >= 3 and menor[0] == maior[0] and set(menor) <= set(maior):
        return True, round(100 * len(menor) / len(maior), 1)
    return False, score


def _evidencia_pessoa(p: dict, detalhe: str) -> dict:
    return {
        "pagina": p.get("pagina", 0),
        "trecho": f"{p.get('nome')} — {detalhe}",
        "funcao": p.get("funcao"),
    }


def _r07_vinculo_familiar(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R07 — Vínculo familiar entre pessoas de empresas distintas.

    Critérios (nomes comparados por _nomes_equivalentes):
    - cônjuge: o cônjuge informado para uma pessoa de A é uma pessoa de B
      (ou vice-versa);
    - filiação: o pai ou a mãe de uma pessoa de A é uma pessoa de B
      (ou vice-versa);
    - filiação comum: pessoas distintas de A e B com o mesmo pai E a mesma
      mãe (possíveis irmãos). Exige os dois nomes, para reduzir homônimos.

    Vínculos familiares dentro de uma mesma empresa não são achado.
    """
    achados: list[Achado] = []
    vistos: set[tuple] = set()

    def registrar(chave, tipo, descricao, valor, pa, pb, score, det_a, det_b):
        if chave in vistos:
            return
        vistos.add(chave)
        achados.append(Achado(
            regra_codigo="R07",
            regra_descricao=descricao,
            empresa_a_id=a.id, empresa_a_nome=a.nome,
            empresa_b_id=b.id, empresa_b_nome=b.nome,
            campo=tipo,
            valor=valor,
            similaridade=round(score / 100, 3),
            evidencia_a=_evidencia_pessoa(pa, det_a),
            evidencia_b=_evidencia_pessoa(pb, det_b),
            nota=(
                "Vínculo familiar inferido por comparação de nomes. Recomenda-se confirmar a "
                "identidade das pessoas (CPF, certidões) antes de qualquer conclusão."
            ),
        ))

    for pa in a.pessoas:
        for pb in b.pessoas:
            # Cônjuge de uma pessoa é a outra. O casal é um vínculo só, mesmo
            # que cada lado informe o outro como cônjuge.
            for x, y, x_em_a in ((pa, pb, True), (pb, pa, False)):
                ok, score = _nomes_equivalentes(x.get("conjuge"), y.get("nome"))
                if ok:
                    registrar(
                        ("conjuge", id(pa), id(pb)), "conjuge",
                        "Cônjuge de pessoa vinculada a uma empresa figura nos documentos de outra empresa",
                        f"{x['nome']} (cônjuge: {x['conjuge']}) / {y['nome']}",
                        pa, pb, score,
                        f"cônjuge informado: {pa.get('conjuge')}" if x_em_a else "pessoa indicada como cônjuge",
                        "pessoa indicada como cônjuge" if x_em_a else f"cônjuge informado: {pb.get('conjuge')}",
                    )

            # Pai ou mãe de uma pessoa é a outra
            for x, y, x_em_a in ((pa, pb, True), (pb, pa, False)):
                for campo, parentesco in (("filiacao_pai", "pai"), ("filiacao_mae", "mãe")):
                    ok, score = _nomes_equivalentes(x.get(campo), y.get("nome"))
                    if ok:
                        registrar(
                            ("filiacao", id(x), id(y), campo), "filiacao",
                            "Pessoa vinculada a uma empresa é genitor(a) de pessoa vinculada a outra empresa",
                            f"{y['nome']} ({parentesco} de {x['nome']})",
                            pa, pb, score,
                            f"{parentesco}: {x.get(campo)}" if x_em_a else f"indicada como {parentesco}",
                            f"indicada como {parentesco}" if x_em_a else f"{parentesco}: {x.get(campo)}",
                        )

            # Mesmo pai e mesma mãe (possíveis irmãos), sendo pessoas diferentes
            if all(p.get(k) for p in (pa, pb) for k in ("filiacao_pai", "filiacao_mae")):
                mesma_pessoa, _ = _nomes_equivalentes(pa.get("nome"), pb.get("nome"))
                ok_pai, s_pai = _nomes_equivalentes(pa["filiacao_pai"], pb["filiacao_pai"])
                ok_mae, s_mae = _nomes_equivalentes(pa["filiacao_mae"], pb["filiacao_mae"])
                if ok_pai and ok_mae and not mesma_pessoa:
                    registrar(
                        ("irmaos", id(pa), id(pb)), "filiacao_comum",
                        "Pessoas vinculadas a empresas distintas têm a mesma filiação (possíveis irmãos)",
                        f"{pa['nome']} / {pb['nome']} (pais: {pa['filiacao_pai']} e {pa['filiacao_mae']})",
                        pa, pb, min(s_pai, s_mae),
                        f"pai: {pa['filiacao_pai']}; mãe: {pa['filiacao_mae']}",
                        f"pai: {pb['filiacao_pai']}; mãe: {pb['filiacao_mae']}",
                    )
    return achados


# ---------------------------------------------------------------------------
# R08 — endereço coincidente
# ---------------------------------------------------------------------------

_ABREVIACOES = [
    (r"\bR\b", "RUA"), (r"\bAV\b|\bAVEN\b", "AVENIDA"), (r"\bROD\b", "RODOVIA"),
    (r"\bAL\b", "ALAMEDA"), (r"\bTV\b|\bTRAV\b", "TRAVESSA"), (r"\bPC\b|\bPCA\b", "PRACA"),
    (r"\bQD\b|\bQ\b", "QUADRA"), (r"\bLT\b|\bL\b|\bLTS\b|\bLOTES\b", "LOTE"),
    (r"\bAPTO\b|\bAPT\b|\bAP\b|\bAPARTAMENTO\b", "APTO"), (r"\bED\b|\bEDIF\b|\bEDIFICIO\b", "EDIFICIO"),
    (r"\bST\b|\bSET\b", "SETOR"), (r"\bSL\b", "SALA"), (r"\bBL\b", "BLOCO"),
    (r"\bCJ\b|\bCONJ\b", "CONJUNTO"), (r"\bJD\b", "JARDIM"), (r"\bRES\b", "RESIDENCIAL"),
    (r"\bN\b|\bNO\b|\bNUM\b|\bNUMERO\b|\bCEP\b", " "),
]

_CEP_NO_TEXTO = re.compile(r"\b\d{2}\.?\d{3}-\d{3}\b|\bCEP[:\s]*\d{2}\.?\d{3}-?\d{3}\b")


def _normalizar_endereco(texto: str) -> tuple[str, set[str]]:
    """
    Normaliza um endereço para comparação.

    Returns:
        (palavras sem números, conjunto de números) — o CEP é removido,
        porque a R04 já o compara.
    """
    s = _sem_acentos((texto or "").upper()).replace("º", " ").replace("ª", " ")
    s = _CEP_NO_TEXTO.sub(" ", s)
    s = re.sub(r"(?<=\d)\.(?=\d)", "", s)            # 1.004 → 1004
    s = re.sub(r"[^A-Z0-9]", " ", s)
    for padrao, substituto in _ABREVIACOES:
        s = re.sub(padrao, substituto, s)
    numeros = {str(int(n)) for n in re.findall(r"\d+", s)}
    palavras = " ".join(re.sub(r"\d+", " ", s).split())
    return palavras, numeros


def _enderecos(empresa: Empresa) -> list[tuple[str, dict]]:
    """Endereços da empresa e das pessoas vinculadas, com a origem de cada um."""
    lista = [
        (e.get("valor") or "", {"pagina": e.get("pagina", 0), "trecho": e.get("trecho") or "Endereço da empresa"})
        for e in empresa.enderecos
    ]
    lista += [
        (p["endereco"], {"pagina": p.get("pagina", 0), "trecho": f"Endereço de {p.get('nome')}", "funcao": p.get("funcao")})
        for p in empresa.pessoas if p.get("endereco")
    ]
    return [(t, ev) for t, ev in lista if t.strip()]


def _r08_endereco_coincidente(a: Empresa, b: Empresa) -> list[Achado]:
    """
    R08 — Mesmo endereço em documentos de empresas distintas.

    Compara os endereços das empresas (sede, filiais) e das pessoas vinculadas.

    Critério, após normalização (acentos, pontuação, abreviações e CEP removidos):
    - os números do endereço com menos números (logradouro, número, quadra,
      lote...) estão todos no outro — "Rua T-33, 188" × "Rua T-33, 188, apto
      1004" coincide; "Rua T-33, 188" × "Rua T-33, 190" não;
    - as palavras são ao menos 90% similares (token_set_ratio).
    Endereços sem nenhum número não são comparados (muito genéricos).
    """
    LIMIAR = 90.0
    achados: list[Achado] = []
    vistos: set[tuple] = set()

    enderecos_b = [(t, ev, *_normalizar_endereco(t)) for t, ev in _enderecos(b)]
    for texto_a, ev_a in _enderecos(a):
        palavras_a, numeros_a = _normalizar_endereco(texto_a)
        if not numeros_a or len(palavras_a.split()) < 2:
            continue
        for texto_b, ev_b, palavras_b, numeros_b in enderecos_b:
            if not numeros_b or len(palavras_b.split()) < 2:
                continue
            menor, maior = sorted((numeros_a, numeros_b), key=len)
            if not menor <= maior:
                continue
            score = fuzz.token_set_ratio(palavras_a, palavras_b)
            if score < LIMIAR:
                continue
            chave = (palavras_a, frozenset(numeros_a), palavras_b, frozenset(numeros_b))
            if chave in vistos:
                continue
            vistos.add(chave)
            achados.append(Achado(
                regra_codigo="R08",
                regra_descricao="O mesmo endereço consta em documentos de empresas distintas",
                empresa_a_id=a.id, empresa_a_nome=a.nome,
                empresa_b_id=b.id, empresa_b_nome=b.nome,
                campo="endereco",
                valor=f"{texto_a[:120]} / {texto_b[:120]}",
                similaridade=round(score / 100, 3),
                evidencia_a=ev_a,
                evidencia_b=ev_b,
                nota=(
                    "Endereço coincidente pode decorrer de edifício comercial, escritório de "
                    "contabilidade ou domicílio comum. O servidor deve avaliar o contexto."
                ),
            ))
    return achados
