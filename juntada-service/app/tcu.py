"""
Consulta automática da Consulta Consolidada de Pessoa Jurídica (TCU) — fase 2.

Uma chamada traz quatro cadastros (TCU Inidôneos, CNJ/CNIA, CEIS e CNEP) e
o PDF oficial. A API não envia cabeçalho CORS, então não pode ser chamada
pelo navegador: precisa sair do backend.

O servidor de produção não tem internet. A consulta só é feita com
JUNTADA_CONSULTA_TCU=1, depois que a TI liberar a saída para
certidoes-apf.apps.tcu.gov.br. Desligada, o servidor baixa a consulta pelo
site e a envia como as demais certidões.
"""

import base64
import json
import os
import urllib.request

URL = "https://certidoes-apf.apps.tcu.gov.br/api/rest/publico/certidoes/{cnpj}?seEmitirPDF=true"


class ConsultaIndisponivel(Exception):
    pass


def ativa() -> bool:
    return os.environ.get("JUNTADA_CONSULTA_TCU", "0") == "1"


def consultar(cnpj: str, timeout: float = 30.0) -> bytes:
    """Devolve o PDF oficial da consulta consolidada."""
    if not ativa():
        raise ConsultaIndisponivel(
            "Consulta automática desativada: o servidor não tem acesso à internet "
            "(JUNTADA_CONSULTA_TCU=0). Emita a consulta no site do TCU e envie o PDF."
        )
    try:
        with urllib.request.urlopen(URL.format(cnpj=cnpj), timeout=timeout) as resposta:
            dados = json.loads(resposta.read())
    except Exception as e:
        raise ConsultaIndisponivel(f"Falha ao consultar o TCU: {e}") from e
    if not dados.get("certidaoPDF"):
        raise ConsultaIndisponivel("O TCU não devolveu o PDF da consulta.")
    return base64.b64decode(dados["certidaoPDF"])
