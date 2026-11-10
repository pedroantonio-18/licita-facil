"""
Texto da "Informação" de estimativa e enquadramento, como a SELIT/SECOP junta no SEI.

A redação segue os textos padrão internos da SJGO-SECOP ("Estimativa em Dispensa de
Licitação", "Estimativa em Pregão Eletrônico", "Estimativa Engenharia - Pregão Eletrônico")
e as Informações já assinadas. O que o servidor não informou sai entre colchetes, com fundo
amarelo, para não passar despercebido no SEI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from html import escape

from app.extenso import formatar_reais, valor_com_extenso
from app.regras import LIMITE_ME_EPP, Demanda, Enquadramento, Item

METODOLOGIAS = {
    "media_saneada": "a Média Saneada dos preços obtidos, considerando apenas amostras com Coeficiente de Variação "
                     "igual ou inferior a 25%, garantindo homogeneidade suficiente para representatividade, em "
                     "conformidade com o Manual de Orientação de Pesquisa de Preços (2021) do Superior Tribunal de Justiça",
    "media": "a Média Aritmética dos preços obtidos, considerando apenas amostras com Coeficiente de Variação igual ou "
             "inferior a 25%, garantindo homogeneidade suficiente para representatividade, em conformidade com o Manual "
             "de Orientação de Pesquisa de Preços (2021) do Superior Tribunal de Justiça",
    "mediana": "a mediana dos preços obtidos, nos termos do art. 6º da IN SEGES/ME nº 65/2021",
    "menor": "o menor dos preços obtidos, nos termos do art. 6º da IN SEGES/ME nº 65/2021",
}
NOMES_METODOLOGIAS = {"media_saneada": "Média saneada (CV ≤ 25%)", "media": "Média aritmética (CV ≤ 25%)",
                      "mediana": "Mediana", "menor": "Menor preço"}


@dataclass
class DadosInformacao:
    objeto: str = ""                       # "aquisição de materiais elétricos, destinados a ..."
    doc_referencia: str = ""               # "Estudo Técnico Preliminar - ETP Completo 25169080"
    destinatarios: str = "Senhor Supervisor da Seplo e Senhora Supervisora da Secon,"
    # pesquisa de preços
    fonte: str = "banco_precos"            # "banco_precos" | "seeng"
    relatorio: str = ""                    # nº SEI do Relatório Banco de Preços / planilha da SEENG
    incisos_in65: list[str] = field(default_factory=lambda: ["II"])
    metodologia: str = "media_saneada"
    info_conclusiva: str = ""              # pregão: nº SEI da informação conclusiva do valor estimado
    base_seeng: str = "tabelas_oficiais"   # "tabelas_oficiais" | "contratacoes_similares"
    # enquadramento
    ref_comum: str = ""                    # pregão: onde o ETP/TR define bem/serviço comum ("item D do ETP 25169080")
    # Dispensa por valor é exclusiva para ME/EPP por definição (SELIT); "preferencial" é a redação
    # antiga do texto padrão, mantida como opção
    me_epp_dispensa: str = "exclusiva"     # "exclusiva" | "preferencial"
    incluir_seguridade: bool = True
    pca_referencia: str = ""               # "PCA 2026 (26138914)"
    # fecho
    pedir_tr: bool = True
    encerramento: str = "Respeitosamente,"
    servidor: str = ""
    cargo_servidor: str = ""
    supervisor: str = ""
    cargo_supervisor: str = ""


@dataclass
class Paragrafo:
    texto: str
    tipo: str = "p"            # "p" | "tabela" | "lista" | "fecho" | "destinatario"
    linhas: list[list[str]] = field(default_factory=list)


def _ou(valor: str, rotulo: str) -> str:
    return valor.strip() if valor and valor.strip() else f"[informar {rotulo}]"


def _incisos(lista: list[str]) -> str:
    ordem = [i for i in ("I", "II", "III", "IV", "V", "VI") if i in lista]
    if not ordem:
        return "inciso [informar]"
    if len(ordem) == 1:
        return f"inciso {ordem[0]}"
    return "incisos " + ", ".join(ordem[:-1]) + " e " + ordem[-1]


def _lista_itens(nomes: list[str]) -> str:
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def montar(d: DadosInformacao, e: Enquadramento, natureza: str, itens: list[Item], demandas: list[Demanda]) -> list[Paragrafo]:
    ps: list[Paragrafo] = [Paragrafo(d.destinatarios or "[informar destinatários]", "destinatario")]
    engenharia = natureza in ("servico_engenharia", "obra") or d.fonte == "seeng"
    objeto = _ou(d.objeto, "objeto")
    doc = _ou(d.doc_referencia, "documento de referência (ETP/DFD/TR e nº SEI)")

    # 1. Objeto
    if engenharia:
        ps.append(Paragrafo(f"Tratam os autos de {objeto}, conforme {doc}."))
    else:
        ps.append(Paragrafo(f"Os presentes autos tratam da {objeto}, conforme {doc}."))

    # 2. Pesquisa de preços
    if d.fonte == "seeng":
        ps.append(Paragrafo(
            "Por se tratar de serviços de engenharia, a estimativa de preços foi elaborada pela SEENG - Seção de "
            f"Engenharia, consoante {_ou(d.relatorio, 'planilha orçamentária da SEENG e nº SEI')}, conforme Decreto "
            "nº 7.983, de 8 de abril de 2013."))
        if d.base_seeng == "contratacoes_similares":
            ps.append(Paragrafo(
                "De acordo com a SEENG, todos os custos para a execução do serviço pretendido foram obtidos por meio de "
                "contratações similares feitas pela Administração Pública, em execução ou concluídas no período de "
                "1 (um) ano anterior à data da pesquisa de preços, observado o índice de atualização de preços "
                "correspondente, conforme art. 23, § 2º, inciso III, da Lei nº 14.133/2021."))
        else:
            ps.append(Paragrafo(
                "De acordo com a SEENG, todos os custos para a execução do serviço pretendido foram obtidos por meio de "
                "tabelas referenciais oficiais (SINAPI, AGETOP etc.)."))
    else:
        ps.append(Paragrafo(
            "Para a composição da estimativa de preços, foram considerados valores de objetos semelhantes ou de mesma "
            "natureza, cujas especificações demonstram compatibilidade com o objeto pretendido. Essa análise foi "
            "realizada após criteriosa avaliação dos dados coletados, disponíveis no Relatório Banco de Preços "
            f"({_ou(d.relatorio, 'nº SEI do relatório')}), observando-se a compatibilização de especificações, "
            "quantidades e condições dos itens, de modo a refletir o preço corrente de mercado e assegurar a "
            f"economicidade da contratação, conforme disposto nos arts. 4º e 5º, {_incisos(d.incisos_in65)}, da IN "
            "SEGES/ME nº 65/2021."))
        ps.append(Paragrafo(f"A metodologia adotada para apuração do valor estimado foi "
                            f"{METODOLOGIAS.get(d.metodologia, METODOLOGIAS['media_saneada'])}."))
        if e.modalidade != "dispensa" and d.info_conclusiva:
            ps.append(Paragrafo("As disposições sobre a composição da estimativa e a metodologia estão detalhadas na "
                                f"informação conclusiva sobre o Valor Estimado da Licitação ({d.info_conclusiva})."))

    # 3. Valor e enquadramento
    valor = valor_com_extenso(e.valor_estimado)
    if e.modalidade == "dispensa":
        ps.append(Paragrafo(
            f"Dessa forma, a despesa foi estimada em {valor}, enquadrando-se na hipótese de Dispensa de Licitação, nos "
            f"termos do art. 75, inciso {e.inciso}, da Lei nº 14.133/2021, a ser realizada preferencialmente por meio "
            "de dispensa eletrônica."))
    else:
        ps.append(Paragrafo(f"Dessa forma, a despesa foi estimada em {valor}"
                            + (", conforme discriminado abaixo." if len(itens) > 1 else ".")))
    if len(itens) > 1:
        ps.append(Paragrafo("", "tabela", [["Item", "Descrição", "Valor estimado (R$)"]] +
                            [[str(n), i.descricao, formatar_reais(i.valor)] for n, i in enumerate(itens, 1)]))

    if e.modalidade == "dispensa":
        if d.incluir_seguridade and e.seguridade is not None:
            ps.append(Paragrafo(
                "Para o caso de contratação de pessoa física, informa-se que o valor correspondente a 20% da Seguridade "
                f"Social é de {valor_com_extenso(e.seguridade)}, conforme art. 5º, inciso III, da IN SEGES/ME nº 116/2021."))
        if d.me_epp_dispensa == "exclusiva":
            ps.append(Paragrafo("A presente contratação será destinada exclusivamente para ME/EPP."))
        else:
            ps.append(Paragrafo("A presente contratação será processada preferencialmente para ME/EPP, considerando a "
                                "disponibilidade no sistema de Dispensa Eletrônica."))
        ps.append(Paragrafo(
            "Ressalta-se que não será utilizado o Sistema de Registro de Preços (SRP) para esta aquisição, em razão do "
            "disposto no § 6º do art. 82 da Lei nº 14.133/2021, que condiciona o uso do SRP, em casos de dispensa, à "
            "participação de mais de um órgão ou entidade, hipótese que não se aplica ao presente caso."))
        ps.extend(_pca(d, e, demandas))
    else:
        # no pregão o PCA só entra quando foi ele que levou à licitação (soma de demandas semelhantes)
        if any(not x.propria for x in demandas):
            ps.extend(_pca(d, e, demandas))
        if natureza in ("servico_engenharia", "obra"):
            ps.append(Paragrafo(
                f"O objeto dos autos foi definido no {_ou(d.ref_comum, 'documento e item (ex.: ETP, letra E.1)')} como "
                "sendo serviço comum de engenharia, assim a despesa fica enquadrada em pregão eletrônico, conforme "
                "art. 6º, incisos XXI, \"a\", e XLI, c/c art. 29, caput e parágrafo único, da Lei nº 14.133/2021."))
        else:
            tipo = "bem comum" if natureza == "bem" else "serviço comum"
            ps.append(Paragrafo(
                f"Considerando que o objeto dos autos possui natureza de {tipo}, cujos padrões de desempenho e qualidade "
                "podem ser objetivamente definidos no edital, por meio de especificações reconhecidas e usuais do "
                f"mercado, conforme {_ou(d.ref_comum, 'item do TR ou do ETP')}, a contratação enquadra-se na modalidade "
                "Pregão Eletrônico, nos termos do art. 6º, inciso XLI, combinado com o art. 29, caput, da Lei nº "
                "14.133/2021."))
        ps.append(Paragrafo(_me_epp_pregao(e, itens)))

    # 4. Pedidos e fecho
    ps.append(Paragrafo("Solicita-se a verificação da disponibilidade orçamentária para a referida despesa."))
    if d.pedir_tr:
        ps.append(Paragrafo("Havendo disponibilidade, solicita-se o encaminhamento à Secon para elaboração do Termo de "
                            "Referência."))
    ps.append(Paragrafo(d.encerramento or "Respeitosamente,", "fecho"))
    for nome, cargo in ((d.servidor, d.cargo_servidor), (d.supervisor, d.cargo_supervisor)):
        if nome:
            ps.append(Paragrafo(nome + (f"\n{cargo}" if cargo else ""), "assinatura"))
    return ps


def _pca(d: DadosInformacao, e: Enquadramento, demandas: list[Demanda]) -> list[Paragrafo]:
    ano = e.exercicio
    ref = d.pca_referencia.strip() if d.pca_referencia.strip() else f"PCA {ano}"
    pca = [x for x in demandas if not x.ja_contratada]
    feitas = [x for x in demandas if x.ja_contratada]
    ps = []
    if not any(not x.propria for x in demandas) and not any(x.propria for x in demandas):
        ps.append(Paragrafo(
            f"Em consulta ao {ref} para o exercício de {ano}, não foram identificadas aquisições ou serviços com "
            "características semelhantes ao objeto dos autos que possam ser fornecidos por empresas do mesmo ramo de "
            "atividade. Assim, confirma-se que o valor estimado não ultrapassa o limite legal para dispensa de "
            f"licitação, considerando o exercício financeiro de {ano}, e não configura fracionamento indevido de despesa."))
        return ps
    if pca:
        ps.append(Paragrafo(
            f"Em consulta ao {ref} para o exercício de {ano}, foram identificadas as seguintes demandas semelhantes, "
            "observado o regramento do art. 4º da IN SEGES/ME nº 67/2021:"))
        ps.append(Paragrafo("", "tabela", [["Demanda", "Origem", f"Desembolso {ano} (R$)"]] +
                            [[x.descricao, x.origem, formatar_reais(x.valor)] for x in pca]))
    for x in feitas:
        ps.append(Paragrafo(
            f"Também, já foi realizada a contratação de {x.descricao}, no valor total de {valor_com_extenso(x.valor)}, "
            f"conforme {x.origem}."))
    limite = f"R$ {formatar_reais(e.limite)}"
    decreto = f", conforme o {e.decreto}" if e.decreto else ""
    if e.fracionamento_ok:
        ps.append(Paragrafo(
            f"Assim, a soma total dos valores em questão, {valor_com_extenso(e.soma_exercicio)}, não ultrapassa o limite "
            f"legal para dispensa de licitação, atualmente de {limite}{decreto}, considerando o exercício financeiro de "
            f"{ano}, e não configura fracionamento indevido de despesa."))
    else:
        ps.append(Paragrafo(
            f"Assim, a soma total dos valores em questão, {valor_com_extenso(e.soma_exercicio)}, ultrapassa o limite legal "
            f"para dispensa de licitação, atualmente de {limite}{decreto}, considerando o exercício financeiro de {ano}, "
            "razão pela qual a contratação deve ser realizada mediante licitação, nos termos do art. 4º da IN SEGES/ME "
            "nº 67/2021."))
    return ps


def _me_epp_pregao(e: Enquadramento, itens: list[Item]) -> str:
    base = "Nos termos do art. 48, inciso I, da LC nº 123/2006, "
    destino = ("destinada exclusivamente às microempresas, empresas de pequeno porte e sociedades cooperativas "
               "enquadradas no art. 34 da Lei nº 11.488/2007")
    limite = f"R$ {formatar_reais(LIMITE_ME_EPP)}"
    regra = e.me_epp["regra"]
    if regra == "exclusiva":
        sujeito = "nenhum item ultrapassou" if len(itens) > 1 else "o valor estimado não ultrapassou"
        return f"{base}como {sujeito} o valor de {limite}, a licitação será {destino}."
    if regra == "ampla":
        sujeito = "os itens individualmente ultrapassaram" if len(itens) > 1 else "o valor estimado ultrapassou"
        return f"{base}como {sujeito} o valor de {limite}, a licitação será destinada à ampla participação."
    art = lambda n: ("o item " if n == 1 else "os itens ")
    partes = []
    if e.me_epp["exclusivos"]:
        n = len(e.me_epp["exclusivos"])
        partes.append(f"{art(n)}{_lista_itens(e.me_epp['exclusivos'])}, por não ultrapassar{'' if n == 1 else 'em'} o valor de "
                      f"{limite}, {'será destinado' if n == 1 else 'serão destinados'} exclusivamente às microempresas, empresas "
                      "de pequeno porte e sociedades cooperativas enquadradas no art. 34 da Lei nº 11.488/2007")
    if e.me_epp.get("cotas"):
        n = len(e.me_epp["cotas"])
        partes.append(f"{art(n)}{_lista_itens(e.me_epp['cotas'])}, de natureza divisível e valor superior a {limite}, "
                      f"{'terá' if n == 1 else 'terão'} cota reservada de até 25% (vinte e cinco por cento) do quantitativo para "
                      "microempresas e empresas de pequeno porte, nos termos do art. 48, inciso III, da LC nº 123/2006, em "
                      "percentual a ser definido motivadamente pelo setor requisitante")
    if e.me_epp["amplos"]:
        n = len(e.me_epp["amplos"])
        partes.append(f"{art(n)}{_lista_itens(e.me_epp['amplos'])}, de valor superior a {limite} e natureza indivisível, "
                      f"{'será destinado' if n == 1 else 'serão destinados'} à ampla participação")
    if e.me_epp.get("sem_beneficio"):
        n = len(e.me_epp["sem_beneficio"])
        partes.append(f"{art(n)}{_lista_itens(e.me_epp['sem_beneficio'])}, de valor superior a R$ 4.800.000,00, não "
                      f"{'terá' if n == 1 else 'terão'} tratamento favorecido, na forma do art. 4º, § 1º, inciso I, da Lei nº 14.133/2021")
    texto = "; ".join(partes)
    return f"Nos termos do art. 48 da LC nº 123/2006, {texto}."


# ---------------------------------------------------------------------------
# Saída para o SEI (mesmo formato testado nas minutas: Times 12, formatação direta)
# ---------------------------------------------------------------------------

FONTE = "font-family: 'Times New Roman', Times, serif; font-size: 12pt;"
AMARELO = "background-color: #ffff00;"


def _realce_pendencias(texto: str) -> str:
    import re
    return re.sub(r"\[informar[^\]]*\]", lambda m: f'<span style="{AMARELO}">{m.group(0)}</span>', texto)


def html_sei(ps: list[Paragrafo]) -> str:
    out = []
    for p in ps:
        if p.tipo == "tabela":
            linhas = []
            for i, linha in enumerate(p.linhas):
                cel = "".join(
                    f'<td style="border: 1px solid #000; padding: 2px 6px;"><p class="Tabela_Texto_Centralizado" '
                    f'style="{FONTE} margin: 0; text-align: {"right" if j == len(linha) - 1 and i else "center"};">'
                    f'{"<b>" if i == 0 else ""}{escape(c)}{"</b>" if i == 0 else ""}</p></td>'
                    for j, c in enumerate(linha))
                linhas.append(f"<tr>{cel}</tr>")
            out.append('<table style="border-collapse: collapse; margin: 6pt auto;" border="1">' + "".join(linhas) + "</table>")
        elif p.tipo == "destinatario":
            out.append(f'<p class="Texto_Alinhado_Esquerda" style="{FONTE} text-align: left;">{_realce_pendencias(escape(p.texto))}</p>')
        elif p.tipo == "assinatura":
            out.append(f'<p class="Texto_Centralizado" style="{FONTE} text-align: center;">{escape(p.texto).replace(chr(10), "<br>")}</p>')
        else:
            out.append(f'<p class="Texto_Justificado_Recuo_Primeira_Linha" style="{FONTE} text-align: justify; '
                       f'text-indent: 25mm;">{_realce_pendencias(escape(p.texto))}</p>')
    return "\n".join(out)
