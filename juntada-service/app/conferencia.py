"""
Conferência das certidões de uma empresa numa data de referência.

Para cada documento: o CNPJ é da empresa? está válido na data? o resultado
permite a habilitação? Para a empresa: falta algum item obrigatório?

Regras da SELIT (respostas de 04/11/2026):
- Regularidade fiscal, social e trabalhista: o SICAF é a base. Se o
  relatório mostra a certidão válida, ela está coberta; certidão avulsa só
  é necessária para o que estiver vencido ou ausente no SICAF. O SICAF não
  tem validade própria: vale a de cada certidão que ele espelha.
- Estadual é exigida para compra de bens; municipal, para serviços.
- Consolidada do TCU: 30 dias. Falência (quando exigida): validade impressa
  ou, no TJGO, 30 dias.
- Idoneidade: TCU + certidões da CGU, inclusive do CPF dos sócios.

O sistema só aponta; quem decide sobre a habilitação é o servidor.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.certidoes import (
    INDETERMINADO, OUTRO, PENDENTE, POSITIVA, REGULARIDADE, ROTULO_RESULTADO, TIPOS, TIPOS_POR_ID, CertidaoLida,
)
from app.texto import formatar_cnpj

# Situação de cada item, da melhor para a pior
OK = "ok"
ATENCAO = "atencao"      # conferir manualmente (ex.: validade não lida)
PROBLEMA = "problema"    # vencida, positiva, CNPJ de outra empresa…
FALTANDO = "faltando"

GRAVIDADE = {OK: 0, ATENCAO: 1, PROBLEMA: 2, FALTANDO: 3}
ROTULO_SITUACAO_TEXTO = {OK: "OK", ATENCAO: "Conferir", PROBLEMA: "Problema", FALTANDO: "Faltando"}

# Rol mínimo da SELIT; estadual/municipal entram conforme o objeto
BASE_OBRIGATORIAS = ["habilitacao", "federal", "fgts", "trabalhista", "tcu", "cgu"]
POR_OBJETO = {"compras": ["estadual"], "servicos": ["municipal"], "ambos": ["estadual", "municipal"]}


def obrigatorias_padrao(objeto: str = "compras") -> list[str]:
    return BASE_OBRIGATORIAS + POR_OBJETO.get(objeto, [])


PADRAO_OBRIGATORIAS = obrigatorias_padrao("compras")


@dataclass
class Parametros:
    data_referencia: date
    obrigatorias: list[str] = field(default_factory=lambda: list(PADRAO_OBRIGATORIAS))
    dias_consultas: int = 30     # TCU e CGU: válidas por N dias da emissão
    dias_falencia: int = 30      # falência sem validade impressa (TJGO: 30 dias)
    objeto: str = "compras"      # compras | servicos | ambos


@dataclass
class Conferencia:
    certidao: CertidaoLida
    situacao: str
    observacoes: list[str]


def _validade(c: CertidaoLida, p: Parametros) -> None:
    """Completa a validade das certidões que valem por N dias da emissão."""
    tipo = TIPOS_POR_ID.get(c.tipo, OUTRO)
    if c.validade_fim or tipo.validade != "consulta" or not c.emissao:
        return
    dias = getattr(p, tipo.parametro_dias or "dias_consultas")
    c.validade_fim = c.emissao + timedelta(days=dias)
    c.validade_origem = f"{dias} dias da emissão (parâmetro)"


def conferir_certidao(c: CertidaoLida, cnpj_empresa: str, p: Parametros) -> Conferencia:
    tipo = TIPOS_POR_ID.get(c.tipo, OUTRO)
    _validade(c, p)
    problemas: list[str] = []
    atencoes: list[str] = []
    sem_validade = tipo.validade == "nenhuma"

    if c.tipo == OUTRO.id:
        atencoes.append("Documento não identificado — incluído na habilitação jurídica; conferir")
    if not c.texto_lido:
        atencoes.append("Documento digitalizado (sem texto) — conferir manualmente")

    # CNPJ (certidão de pessoa física, ex.: CGU do sócio, traz só CPF)
    if not c.cnpjs:
        if c.cpfs and tipo.id == "cgu":
            pass
        elif tipo.id not in ("habilitacao", OUTRO.id):
            atencoes.append("CNPJ não encontrado no documento")
    elif cnpj_empresa not in c.cnpjs:
        mesma_raiz = [x for x in c.cnpjs if x[:8] == cnpj_empresa[:8]]
        if mesma_raiz and tipo.abrangencia == "raiz":
            pass  # certidão da matriz/filial vale para todos os estabelecimentos
        elif mesma_raiz:
            atencoes.append(
                f"Emitida para outro estabelecimento da empresa ({formatar_cnpj(mesma_raiz[0])}); "
                "este tipo de certidão vale por estabelecimento"
            )
        elif tipo.id not in ("habilitacao", OUTRO.id):
            problemas.append(f"CNPJ do documento ({formatar_cnpj(c.cnpjs[0])}) não é desta empresa")

    # Resultado
    if c.resultado == POSITIVA:
        problemas.append("Resultado positivo (consta débito ou registro)")
    elif c.resultado == PENDENTE:
        atencoes.append("Um dos sistemas consultados estava indisponível — consultar novamente")
    elif c.resultado == INDETERMINADO and not sem_validade:
        atencoes.append("Não foi possível ler o resultado (negativa/positiva)")
    if c.tipo == "sicaf":
        if c.impedimentos:
            problemas.append("SICAF registra: " + "; ".join(c.impedimentos))
        if any("pendência" in d for d in c.detalhes):
            atencoes.append("SICAF registra pendência — verificar qual nível/documento está pendente")

    # Validade
    if not sem_validade:
        if c.validade_fim and c.validade_fim < p.data_referencia:
            problemas.append(f"Vencida em {c.validade_fim:%d/%m/%Y} (data de referência {p.data_referencia:%d/%m/%Y})")
        elif c.validade_inicio and c.validade_inicio > p.data_referencia:
            atencoes.append(f"Validade só começa em {c.validade_inicio:%d/%m/%Y}")
        elif not c.validade_fim:
            atencoes.append("Validade não identificada — conferir manualmente")
    if c.emissao and c.emissao > p.data_referencia:
        atencoes.append(f"Emitida depois da data de referência ({c.emissao:%d/%m/%Y})")

    situacao = PROBLEMA if problemas else ATENCAO if atencoes else OK
    return Conferencia(certidao=c, situacao=situacao, observacoes=problemas + atencoes)


@dataclass
class ItemChecklist:
    tipo: str
    tipo_nome: str
    obrigatoria: bool
    situacao: str
    observacoes: list[str]
    conferencias: list[Conferencia]
    bloco: int = 2
    fonte: str = ""                        # "sicaf" | "avulsa" | "" — de onde veio a comprovação
    emissao: date | None = None
    validade: date | None = None
    resultado: str = ""                    # rótulo legível
    situacao_automatica: str = ""          # o que o sistema concluiu, antes da decisão do servidor
    conferencia_manual: dict | None = None  # {"justificativa", "registrado_em"}

    def documentos_do_bloco(self) -> list[CertidaoLida]:
        """
        Documentos deste item que vão para o PDF do bloco. Item de regularidade
        coberto pelo SICAF não leva a certidão avulsa (a SELIT junta só o SICAF).
        """
        if self.fonte == "sicaf":
            return []
        return [c.certidao for c in self.conferencias if c.certidao.tipo == self.tipo]


def aplicar_conferencias_manuais(itens: list[ItemChecklist], manuais: dict[str, dict]) -> None:
    """
    Aplica as decisões do servidor sobre itens que o sistema não pôde dar
    como OK (ex.: CNJ fora do ar e o servidor consultou o CNIA direto no site;
    certidão dispensada pelo edital).

    A situação automática é preservada e a justificativa vai para as
    observações, para que o relatório mostre as duas.
    """
    for item in itens:
        item.situacao_automatica = item.situacao
        decisao = manuais.get(item.tipo)
        if not decisao or item.situacao == OK:
            continue
        item.conferencia_manual = decisao
        item.situacao = OK
        quando = datetime.fromisoformat(decisao["registrado_em"]).strftime("%d/%m/%Y às %H:%M")
        item.observacoes = [
            f"Conferido manualmente pelo servidor em {quando}: {decisao['justificativa']}",
            f"Situação apontada pelo sistema: {ROTULO_SITUACAO_TEXTO[item.situacao_automatica]}",
        ] + item.observacoes


def _melhor(conferencias: list[Conferencia]) -> Conferencia:
    return min(conferencias, key=lambda c: (GRAVIDADE[c.situacao], -(c.certidao.emissao or date.min).toordinal()))


def _item_simples(tipo, do_tipo, obrigatoria) -> "ItemChecklist":
    melhor = _melhor(do_tipo)
    observacoes = list(melhor.observacoes)
    if len(do_tipo) > 1:
        observacoes.append(f"{len(do_tipo)} documentos deste tipo; considerado o de melhor situação")
    c = melhor.certidao
    return ItemChecklist(tipo.id, tipo.nome, obrigatoria, melhor.situacao, observacoes, do_tipo,
                         bloco=tipo.bloco, fonte="avulsa" if tipo.id in REGULARIDADE else "",
                         emissao=c.emissao, validade=c.validade_fim,
                         resultado=ROTULO_RESULTADO.get(c.resultado, ""))


def _item_regularidade(tipo, avulsas, sicaf: Conferencia | None, obrigatoria, p) -> "ItemChecklist | None":
    """Regularidade coberta pelo SICAF (se válida nele) ou por certidão avulsa."""
    if not obrigatoria and not avulsas:
        return None   # não exigida para este objeto e nenhuma certidão enviada
    validade_sicaf = sicaf.certidao.sicaf_validades.get(tipo.id) if sicaf else None
    sicaf_utilizavel = sicaf is not None and sicaf.situacao != PROBLEMA
    avulsa = _melhor(avulsas) if avulsas else None

    # SICAF válido cobre o item: a SELIT junta só o relatório, sem a certidão avulsa
    if sicaf_utilizavel and validade_sicaf and validade_sicaf >= p.data_referencia:
        observacoes = [f"Válida pelo SICAF até {validade_sicaf:%d/%m/%Y}"]
        if avulsas:
            observacoes.append("Certidão avulsa enviada não entra no PDF: o SICAF já comprova")
        return ItemChecklist(
            tipo.id, tipo.nome, obrigatoria, OK, observacoes, [sicaf] + list(avulsas),
            bloco=tipo.bloco, fonte="sicaf", emissao=sicaf.certidao.emissao, validade=validade_sicaf,
            resultado="Válida no SICAF",
        )
    if avulsa:
        item = _item_simples(tipo, avulsas, obrigatoria)
        if validade_sicaf:
            item.observacoes.append(f"No SICAF, vencida em {validade_sicaf:%d/%m/%Y}")
        return item
    if not obrigatoria:
        return None
    if sicaf and validade_sicaf:
        motivo = (f"Vencida no SICAF em {validade_sicaf:%d/%m/%Y} — juntar certidão avulsa atualizada"
                  if sicaf_utilizavel else "SICAF com impedimento — conferir")
        return ItemChecklist(tipo.id, tipo.nome, True, PROBLEMA, [motivo], [sicaf], bloco=tipo.bloco,
                             fonte="sicaf", emissao=sicaf.certidao.emissao, validade=validade_sicaf,
                             resultado="Vencida no SICAF")
    motivo = ("O SICAF não informa esta certidão — juntar certidão avulsa" if sicaf
              else "Certidão obrigatória não encontrada (nem certidão avulsa, nem SICAF)")
    return ItemChecklist(tipo.id, tipo.nome, True, FALTANDO, [motivo], [sicaf] if sicaf else [], bloco=tipo.bloco)


def montar_checklist(conferencias: list[Conferencia], p: Parametros) -> list[ItemChecklist]:
    """
    Um item por tipo, na ordem dos blocos de juntada. Se houver mais de um
    documento do mesmo tipo, vale o de melhor situação; os demais continuam
    listados. Documentos não identificados entram na habilitação jurídica.
    """
    sicafs = [c for c in conferencias if c.certidao.tipo == "sicaf"]
    sicaf = _melhor(sicafs) if sicafs else None

    itens: list[ItemChecklist] = []
    for tipo in sorted(TIPOS + [OUTRO], key=lambda t: (t.bloco, t.ordem)):
        do_tipo = [c for c in conferencias if c.certidao.tipo == tipo.id]
        obrigatoria = tipo.id in p.obrigatorias

        if tipo.id in REGULARIDADE:
            item = _item_regularidade(tipo, do_tipo, sicaf, obrigatoria, p)
            if item:
                itens.append(item)
            continue
        if tipo.id == "habilitacao" and not do_tipo and any(c.certidao.tipo == OUTRO.id for c in conferencias):
            continue  # documentos não identificados cobrem o bloco 1 (com pedido de conferência)
        if not do_tipo:
            if obrigatoria:
                itens.append(ItemChecklist(tipo.id, tipo.nome, True, FALTANDO,
                                           ["Documento obrigatório não encontrado entre os arquivos"], [],
                                           bloco=tipo.bloco))
            continue
        item = _item_simples(tipo, do_tipo, obrigatoria or (tipo.id == OUTRO.id and "habilitacao" in p.obrigatorias))
        if tipo.id == "cgu":
            pfs = sorted({cpf for c in do_tipo for cpf in c.certidao.cpfs if not c.certidao.cnpjs})
            item.observacoes.append(
                f"{len(pfs)} certidão(ões) de pessoa física; conferir se há uma para cada sócio, "
                "administrador e responsável legal do SICAF"
            )
        itens.append(item)
    return itens


def situacao_geral(itens: list[ItemChecklist]) -> str:
    relevantes = [i.situacao for i in itens if i.obrigatoria or i.situacao != OK]
    return max(relevantes, key=GRAVIDADE.get) if relevantes else OK
