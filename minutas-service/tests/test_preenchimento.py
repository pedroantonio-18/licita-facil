from app.modelo import ler_modelo
from app.montagem import montar
from app.preenchimento import DadosCaso, preencher
from tests import modelo_ficticio

DADOS = DadosCaso(processo="0000001-11.2026.4.01.8006", numero="1/2026", objeto="serviço fictício de teste",
                  valor_total="1.000,00", data_sessao="10/12/2026", criterio="menor preço global", inciso="II",
                  signatario="SERVIDOR FICTÍCIO", cargo="Supervisor de Seção")


def _minuta(dados=DADOS, temas=None):
    m = ler_modelo(modelo_ficticio.aviso_com_capa())
    return m, montar(m, preencher(m, dados, temas))


def _texto(mi, inicio):
    return next(b.texto for b in mi.blocos if b.texto.startswith(inicio))


def test_capa_preenchida_no_formato_da_sjgo():
    _, mi = _minuta()
    textos = [b.texto for b in mi.blocos]
    assert textos[:12] == [
        "AVISO DE CONTRATAÇÃO", "DIRETA", "1/2026",
        "CONTRATANTE (UASG)", "JUSTIÇA FEDERAL DE 1ª INSTÂNCIA/GO (090022)",
        "OBJETO", "Serviço fictício de teste",          # valor realçado de registro de preços não some
        "VALOR TOTAL DA CONTRATAÇÃO", "R$ 1.000,00",
        "DATA DA SESSÃO PÚBLICA", "De 10/12/2026",
        "CRITÉRIO DE JULGAMENTO:",
    ]
    assert _texto(mi, "Menor preço") == "Menor preço global"


def test_corpo_com_dados_fixos_processo_e_numero():
    _, mi = _minuta()
    assert "JUSTIÇA FEDERAL DE 1ª INSTÂNCIA/GO" in [b.texto for b in mi.blocos]
    assert _texto(mi, "AVISO DE CONTRATAÇÃO DIRETA Nº") == "AVISO DE CONTRATAÇÃO DIRETA Nº 1/2026"
    assert _texto(mi, "(Processo") == "(Processo Administrativo n° 0000001-11.2026.4.01.8006)"
    assert _texto(mi, "Torna-se público") == (
        "Torna-se público que o(a) JUSTIÇA FEDERAL DE 1ª INSTÂNCIA/GO, por meio do(a) Seção de Contratações Públicas, "
        "sediado(a) Rua 19, nº 244, Setor Central, CEP 74030-090, Goiânia-GO, e-mail: secop.go@trf1.jus.br, "
        "realizará Dispensa Eletrônica, com critério de julgamento menor preço global, na hipótese do art. 75, "
        "inciso II, nos termos da Lei nº 14.133, de 2021, e demais normas aplicáveis.")   # sem ",," nem registro de preços
    assert _texto(mi, "O objeto é") == "O objeto é a contratação de serviço fictício de teste."


def test_campo_realcado_no_meio_da_frase_e_preenchido_nao_apagado():
    _, mi = _minuta()
    assert _texto(mi, "O prazo de validade") == (
        "O prazo de validade da proposta não será inferior a 60 (sessenta) dias, a contar da data de sua apresentação.")


def test_assinatura_com_fecho_e_sem_pendencias_dos_campos_do_formulario():
    _, mi = _minuta()
    assert _texto(mi, "Goiânia, data") == "Goiânia, data e horário da assinatura eletrônica.\nSERVIDOR FICTÍCIO\nSupervisor de Seção"
    assert mi.pendencias == []
    fixos = [b for b in mi.blocos if b.alterou_texto_fixo]
    assert fixos == []                      # formulário não conta como alteração de texto fixo


def test_formulario_vazio_deixa_pendencias():
    _, mi = _minuta(DadosCaso())
    assert len([p for p in mi.pendencias if "não preenchido" in p.descricao]) >= 4   # número, processo, objeto, critério...


def test_com_registro_de_precos_mantem_gerenciador():
    _, mi = _minuta(temas={"registro_precos"})
    assert "CONTRATANTE/GERENCIADOR (UASG)" in [b.texto for b in mi.blocos]
    assert ", para registro de preços" in _texto(mi, "Torna-se público")
