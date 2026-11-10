"""Modo "minha IA": o servidor cola a resposta de uma IA que ele mesmo usa (ChatGPT, Claude…)."""
import json

from app.crossing.parecer import validar_parecer
from tests.conftest import empresa_minima, importar

ALFA = "11222333000181"


def test_importacao_manual_registra_a_ferramenta_como_origem(client):
    empresa = empresa_minima("ALFA LTDA", ALFA, cpfs=["52998224725"])
    importar(client, "proc-manual", {**empresa, "modelo": "ChatGPT", "via": "manual"})
    sessao = json.dumps(client.get("/conluio/sessao/proc-manual").json(), ensure_ascii=False)
    assert "ChatGPT (resposta copiada e colada pelo servidor)" in sessao
    assert "Gemini" not in sessao


def test_importacao_pelo_gemini_continua_igual(client):
    importar(client, "proc-gemini", {**empresa_minima("ALFA LTDA", ALFA), "modelo": "gemini-x"})
    assert "Gemini gemini-x (via navegador)" in json.dumps(client.get("/conluio/sessao/proc-gemini").json(), ensure_ascii=False)


def test_parecer_colado_com_texto_em_volta_e_virgula_sobrando():
    corpo = '{"avaliacao_geral": null, "itens": [{"texto": "Coincidência de CPF a verificar; recomenda-se consultar o QSA.", "achados": ["A001"]},]}'
    colado = f"Aqui está o parecer solicitado:\n\n```json\n{corpo}\n```\n\nEspero ter ajudado."
    p = validar_parecer(colado, {"A001"}, modelo="Claude (copiar e colar)")
    assert len(p["aceitos"]) == 1 and p["modelo"] == "Claude (copiar e colar)"


def test_pedido_do_parecer_mascara_cpfs_mas_nao_cnpjs():
    from app.crossing.parecer import mascarar_cpfs, montar_prompt
    assert mascarar_cpfs("CPF 529.982.247-25 e 52998224725") == "CPF ***.982.247-** e ***982247**"
    assert mascarar_cpfs("CNPJ 11222333000181 / 11.222.333/0001-81") == "CNPJ 11222333000181 / 11.222.333/0001-81"
    achado = {"id": "A001", "prioridade": "alta", "regra_codigo": "R02", "regra_descricao": "CPF igual",
              "empresa_a": "ALFA", "empresa_b": "BETA", "campo": "cpf", "valor": "529.982.247-25",
              "evidencia_a": {"trecho": "sócio, CPF 529.982.247-25"}, "evidencia_b": {"trecho": "procurador"}}
    prompt = montar_prompt("proc", [achado], {"E1": "Empresa licitante: ALFA (CNPJ 11222333000181)"})
    assert "529.982.247-25" not in prompt and "***.982.247-**" in prompt and "11222333000181" in prompt


def test_identificacao_ignora_cnpj_do_contador_no_rodape():
    from app.extraction.identificacao import identificar_empresa
    rodape = "Elaborado por: ESCRITÓRIO FICTÍCIO CONTÁBIL LTDA - CNPJ 11.444.777/0001-61"
    paginas = [f"Consulta Nível II Fornecedor CNPJ 11.222.333/0001-81 ALFA FICTÍCIA LTDA\n{rodape}",
               f"Contrato social da ALFA FICTÍCIA LTDA, inscrita no CNPJ sob o nº 11.222.333/0001-81\n{rodape}",
               f"Página 3\n{rodape}", f"Página 4\n{rodape}"]
    r = identificar_empresa(paginas)
    assert r["cnpj"] == "11222333000181" and r["razao_social"] == "ALFA FICTÍCIA LTDA"
