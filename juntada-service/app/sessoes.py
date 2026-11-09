"""
Sessões de juntada em disco.

Cada sessão guarda os PDFs enviados e os parâmetros; a conferência é
refeita a partir dos arquivos sempre que preciso (é determinística e
rápida), então não há resultado intermediário para manter sincronizado.

Estrutura: {JUNTADA_DIR}/{sessao}/sessao.json
                                  /{cnpj}/arquivos/*.pdf

Sessões mais antigas que JUNTADA_RETENCAO_HORAS (padrão 48) são apagadas:
os PDFs finais ficam com o servidor (download e "Arquivos recentes").
"""

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

_PADRAO = Path(__file__).resolve().parents[1] / "data" / "sessoes"


def _raiz() -> Path:
    raiz = Path(os.environ.get("JUNTADA_DIR", _PADRAO))
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def limpar_antigas() -> None:
    limite = time.time() - float(os.environ.get("JUNTADA_RETENCAO_HORAS", 48)) * 3600
    for pasta in _raiz().iterdir():
        if pasta.is_dir() and pasta.stat().st_mtime < limite:
            shutil.rmtree(pasta, ignore_errors=True)


def _validar_id(sessao_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", sessao_id or ""):
        raise KeyError(sessao_id)
    return sessao_id


def criar() -> str:
    sessao_id = uuid.uuid4().hex
    (_raiz() / sessao_id).mkdir()
    salvar(sessao_id, {"empresas": {}})
    return sessao_id


def pasta(sessao_id: str) -> Path:
    p = _raiz() / _validar_id(sessao_id)
    if not p.is_dir():
        raise KeyError(sessao_id)
    return p


def carregar(sessao_id: str) -> dict:
    return json.loads((pasta(sessao_id) / "sessao.json").read_text())


def salvar(sessao_id: str, dados: dict) -> None:
    caminho = _raiz() / _validar_id(sessao_id) / "sessao.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1))


def pasta_arquivos(sessao_id: str, cnpj: str) -> Path:
    p = pasta(sessao_id) / re.sub(r"\D", "", cnpj) / "arquivos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def nome_seguro(nome: str, existentes: set[str]) -> str:
    base = re.sub(r"[^\w.\- ]", "_", Path(nome or "documento.pdf").name).strip() or "documento.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    candidato, n = base, 2
    while candidato in existentes:
        candidato = f"{Path(base).stem} ({n}).pdf"
        n += 1
    return candidato


def remover(sessao_id: str) -> None:
    shutil.rmtree(pasta(sessao_id), ignore_errors=True)
