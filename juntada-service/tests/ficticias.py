"""
Certidões FICTÍCIAS no texto dos modelos oficiais de cada órgão, para teste.

Os textos seguem os modelos públicos (Receita/PGFN, Caixa, TST, TCU, TJ),
com empresas e números inventados (CNPJs com dígito verificador válido).
"""

import fitz

ALFA = ("ALFA VEICULOS LTDA", "11.222.333/0001-81")
ALFA_FILIAL = "11.222.333/0002-62"
BETA = ("BETA AUTOMOTORES LTDA", "11.444.777/0001-61")


def pdf(*paginas: str) -> bytes:
    doc = fitz.open()
    for texto in paginas:
        pagina = doc.new_page()
        pagina.insert_textbox(fitz.Rect(50, 50, 545, 800), texto, fontsize=9)
    return doc.tobytes()


def federal(empresa=ALFA, emitida="05/10/2026", valida_ate="03/04/2027", tipo="NEGATIVA"):
    titulo = {
        "NEGATIVA": "CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO",
        "EFEITO": "CERTIDÃO POSITIVA COM EFEITOS DE NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO",
        "POSITIVA": "CERTIDÃO POSITIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS E À DÍVIDA ATIVA DA UNIÃO",
    }[tipo]
    corpo = ("é certificado que não constam pendências em seu nome, relativas a créditos tributários "
             "administrados pela Secretaria da Receita Federal do Brasil (RFB) e a inscrições em Dívida "
             "Ativa da União (DAU) junto à Procuradoria-Geral da Fazenda Nacional (PGFN).")
    if tipo == "POSITIVA":
        corpo = "constam débitos em nome do sujeito passivo acima identificado."
    return (
        "MINISTÉRIO DA FAZENDA\nSecretaria da Receita Federal do Brasil\nProcuradoria-Geral da Fazenda Nacional\n\n"
        f"{titulo}\n\nNome: {empresa[0]}\nCNPJ: {empresa[1]}\n\n"
        "Ressalvado o direito de a Fazenda Nacional cobrar e inscrever quaisquer dívidas de responsabilidade "
        f"do sujeito passivo acima identificado que vierem a ser apuradas, {corpo}\n"
        "Esta certidão é válida para o estabelecimento matriz e suas filiais.\n"
        f"Emitida às 10:15:32 do dia {emitida} <hora e data de Brasília>.\n"
        f"Válida até {valida_ate}.\nCódigo de controle da certidão: A1B2.C3D4.E5F6.G7H8"
    )


def fgts(empresa=ALFA, cnpj=None, inicio="01/10/2026", fim="30/10/2026", obtida="05/10/2026"):
    return (
        "Certificado de Regularidade do FGTS - CRF\n\n"
        f"Inscrição: {cnpj or empresa[1]}\nRazão Social: {empresa[0]}\n"
        "Endereço: AV CENTRAL 100 / SETOR OESTE / GOIANIA / GO / 74000-100\n\n"
        "A Caixa Econômica Federal, no uso da atribuição que lhe confere o Art. 7, da Lei 8.036, de 11 de "
        "maio de 1990, certifica que, nesta data, a empresa acima identificada encontra-se em situação "
        "regular perante o Fundo de Garantia do Tempo de Servico - FGTS.\n\n"
        f"Validade: {inicio} a {fim}\nCertificação Número: 2026100101234567890123\n"
        f"Informação obtida em {obtida} 10:20:15"
    )


def trabalhista(empresa=ALFA, expedida="05/10/2026", validade="03/04/2027"):
    return (
        "PODER JUDICIÁRIO\nJUSTIÇA DO TRABALHO\n\nCERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\n\n"
        f"Nome: {empresa[0]} (MATRIZ E FILIAIS)\nCNPJ: {empresa[1]}\nCertidão nº: 12345678/2026\n"
        f"Expedição: {expedida}, às 10:30:00\n"
        f"Validade: {validade} - 180 (cento e oitenta) dias, contados da data de sua expedição.\n\n"
        f"Certifica-se que {empresa[0]} (MATRIZ E FILIAIS), inscrito(a) no CNPJ sob o nº {empresa[1]}, "
        "NÃO CONSTA como inadimplente no Banco Nacional de Devedores Trabalhistas."
    )


def tcu(empresa=ALFA, data="05/10/2026", cnj="Nada Consta"):
    return (
        "Consulta Consolidada de Pessoa Jurídica\n"
        "Este relatório tem por objetivo apresentar os resultados consolidados de consultas eletrônicas "
        "realizadas diretamente nos bancos de dados dos respectivos cadastros.\n"
        f"{data} 11:59:29\nConsulta realizada em:\nInformações da Pessoa Jurídica:\n"
        f"Razão Social: {empresa[0]}\nCNPJ: {empresa[1]}\nResultados da Consulta Eletrônica:\n"
        "Órgão Gestor: TCU\nCadastro: Licitantes Inidôneos\nResultado da consulta: Nada Consta\n"
        "Para acessar a certidão original no portal do órgão gestor, clique AQUI.\n"
        "Órgão Gestor: CNJ\nCadastro: CNIA - Cadastro Nacional de Condenações Cíveis por Ato de Improbidade "
        f"Administrativa e Inelegibilidade\nResultado da consulta: {cnj}\n"
        "Para acessar a certidão original no portal do órgão gestor, clique AQUI.\n"
        "Órgão Gestor: Portal da Transparência\nCadastro: Cadastro Nacional de Empresas Inidôneas e Suspensas\n"
        "Resultado da consulta: Nada Consta\nPara acessar a certidão original no portal do órgão gestor, clique AQUI.\n"
        "Órgão Gestor: Portal da Transparência\nCadastro: CNEP - Cadastro Nacional de Empresas Punidas\n"
        "Resultado da consulta: Nada Consta\nPara acessar a certidão original no portal do órgão gestor, clique AQUI.\n"
        "Obs: A consulta consolidada de pessoa jurídica visa atender aos princípios de simplificação."
    )


def falencia(empresa=ALFA, data_extenso="05 de outubro de 2026", consta=False):
    resultado = "CONSTA o registro de pedido de recuperação judicial" if consta else "NADA CONSTA"
    return (
        "PODER JUDICIÁRIO DO ESTADO DE GOIÁS\nTRIBUNAL DE JUSTIÇA\n\n"
        "CERTIDÃO DE DISTRIBUIÇÃO - FALÊNCIA, CONCORDATA E RECUPERAÇÃO JUDICIAL\n\n"
        f"CERTIFICA que, revendo os registros de distribuição, em nome de {empresa[0]}, CNPJ {empresa[1]}, "
        f"{resultado} até a presente data.\n\nGoiânia, {data_extenso}."
    )


SOCIO_CPF = "529.982.247-25"


def contrato_social(empresa=ALFA):
    return (
        f"CONTRATO SOCIAL DE CONSTITUIÇÃO DE SOCIEDADE EMPRESÁRIA LIMITADA\n{empresa[0]}\n"
        f"CLÁUSULA I - DO NOME EMPRESARIAL: {empresa[0]}, CNPJ {empresa[1]}.\n"
        "CLÁUSULA IX - Em caso de falência ou recuperação judicial de qualquer sócio, suas quotas serão liquidadas. "
        "A sociedade manterá alvará junto à prefeitura municipal."
    )


def sicaf(empresa=ALFA, emitido="05/10/2026", federal="09/02/2027", fgts="29/10/2026",
          trabalhista="20/02/2027", estadual="24/01/2027", municipal="24/02/2027", impedimento="Nada Consta"):
    """Declaração "Situação do Fornecedor" do SICAF, no layout real (texto extraído do PDF)."""
    linha = lambda rotulo, data: f"{rotulo}\nValidade:\n{data}\nAutomática\n" if data else f"{rotulo}\nValidade:\n"
    return (
        "Sistema de Cadastramento Unificado de Fornecedores - SICAF\nDados do Fornecedor\n"
        f"CNPJ:\n{empresa[1]}\nRazão Social:\n{empresa[0]}\nSituação do Fornecedor: Credenciado\n"
        "Data de Vencimento do Cadastro: 19/04/2027\nOcorrências e Impedimentos\nOcorrência:\nNada Consta\n"
        f"Impedimento de Licitar:\n{impedimento}\nNíveis cadastrados:\nIII - Regularidade Fiscal e Trabalhista Federal\n"
        + linha("Receita Federal e PGFN", federal) + linha("FGTS", fgts) + linha("Trabalhista", trabalhista)
        + "IV - Regularidade Fiscal Estadual/Distrital e Municipal\n"
        + linha("Receita Estadual/Distrital", estadual) + linha("Receita Municipal", municipal)
        + f"Declaração\nEmitido em: {emitido} 15:55\nCPF: 111.XXX.XXX-35 Nome: FULANO CONSULTOR"
    )


def estadual(empresa=ALFA, data_extenso="5 OUTUBRO DE 2026"):
    """Layout real da Secretaria da Economia de Goiás: data sem "de" após o dia e validade em dias."""
    return (
        "ESTADO DE GOIAS\nSECRETARIA DE ESTADO DA ECONOMIA\nSUBSECRETARIA DA RECEITA ESTADUAL\n"
        "CERTIDAO DE DEBITO INSCRITO EM DIVIDA ATIVA - NEGATIVA\nNR. CERTIDÃO: Nº 12345678\n"
        f"IDENTIFICAÇÃO:\nNOME:\nCNPJ\n{empresa[0]}\n{empresa[1]}\n"
        "DESPACHO (Certidao valida para a matriz e suas filiais):\nNAO CONSTA DEBITO\n"
        "FUNDAMENTO LEGAL:\nconstitui documento habil para comprovar a regularidade fiscal perante a "
        "Fazenda Publica Estadual, nos termos do inciso III do art. 68 da Lei nr. 14.133, de 01 de abril de 2021.\n"
        "SEGURANÇA:\nCertidao VALIDA POR 120 DIAS.\nEMITIDA VIA INTERNET\n"
        f"LOCAL E DATA: GOIANIA, {data_extenso}\nHORA: 16:52:23:6"
    )


def cgu(empresa=ALFA, cpf=None, emitida="05/10/2026", validade="04/11/2026"):
    """Layout real da Certidão Negativa Correcional (certidoes.cgu.gov.br).
    Mesmo layout para empresa e pessoa física (conferido com certidões reais das duas)."""
    nome, doc = ("SÓCIO FICTÍCIO DA SILVA", cpf) if cpf else (empresa[0], empresa[1])
    return (
        "Certidão Negativa Correcional\n"
        "Certidão - Entes Privados (ePAD, CGU-PJ, CEIS, CNEP e CEPIM)\n"
        f"Consultado: {nome}\nCPF/CNPJ: {doc}\n"
        "Certifica-se que, em consulta aos sistemas ePAD e CGU-PJ e aos cadastros CEIS, CNEP e CEPIM,\n"
        "mantidos pela Corregedoria-Geral da União, NÃO CONSTAM registros de penalidades vigentes ou de\n"
        "procedimentos acusatórios em andamento, relativos ao CPF/CNPJ consultado.\n"
        f"Certidão emitida às 16:53:23 do dia {emitida} , com validade até o dia {validade}.\n"
        "CONTROLADORIA-GERAL DA UNIÃO"
    )

def municipal_goiania(empresa=ALFA, valida_ate="01/02/2027", data_extenso="4 DE NOVEMBRO DE 2026"):
    """Layout real da Certidão Conjunta da Prefeitura de Goiânia (fecho "GOIANIA(GO), ...")."""
    return (
        "PREFEITURA MUNICIPAL DE GOIÂNIA\nSECRETARIA MUNICIPAL DA FAZENDA\n"
        "CERTIDÃO CONJUNTA DE REGULARIDADE FISCAL\nNEGATIVA DE DÉBITOS DE QUALQUER NATUREZA\n"
        "PESSOA JURÍDICA\nNÚMERO DA CERTIDÃO: 1.234.567-8\n"
        f"Prazo de Validade: até {valida_ate}\nCNPJ: {empresa[1]}\n"
        "Certifica-se que até a presente data NÃO CONSTA DÉBITO VENCIDO OU A VENCER referente a débitos de "
        "qualquer natureza administrados pela Prefeitura Municipal de Goiânia para este CPF ou CNPJ, nos termos "
        "da Lei Complementar Municipal nº 344 de 30/09/2021 (Código Tributário Municipal).\n"
        f"GOIANIA(GO), {data_extenso}\n"
        "ESTA CERTIDÃO É GRATUITA E EMITIDA ELETRONICAMENTE"
    )


def falencia_tjgo(empresa=ALFA, data="28/11/2025", data_extenso="28 de novembro de\n2025"):
    """Layout real da certidão do TJGO para licitação (2 páginas; título não cita falência)."""
    rodape = (f"Tribunal de Justiça do Estado de Goiás\nDocumento Publicado Digitalmente em {data} - 14:32:24\n"
              "Localizar pelo código: 000000000000, no endereço: https://projudi.tjgo.jus.br/CertidaoPublica")
    return (
        "Estado de Goiás\nPoder Judiciário\nTODAS AS COMARCAS\nCERTIDÃO PARA LICITAÇÃO PÚBLICA\nNEGATIVA\n"
        "CERTIFICA a requerimento da parte interessada que, revendo os registros do banco de\n"
        "dados informatizado do Sistema Processual Eletrônico do TJGO, pesquisando as ações de\n"
        "Falência de Empresários, Sociedades Empresariais, ME e EPP; Recuperação Extrajudicial;\n"
        "e Recuperação Judicial em andamento, verifica-se NADA CONSTAR em nome de:\nIdentificação:\n"
        "NADA MAIS. É o que foi pedido para certificar, de que se reporta e da fé.\n"
        f"Dada e passada nesta Cidade e Comarca, do Estado de Goiás, em {data_extenso}.\n"
        f"Requerente\n: {empresa[0]}\nCNPJ\n: {empresa[1]}\n" + rodape
    ), (
        "14:32:22  ESCRIVÃ FICTÍCIA 0000000\nPRAZO DE VALIDADE: 30 DIAS\n"
        "Valor da certidão\n:\nR$ R$ 55,08\n" + rodape
    )
