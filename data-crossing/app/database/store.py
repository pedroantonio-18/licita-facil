"""
Persistência das sessões de análise em SQLite.

Substitui o dicionário _sessoes em memória: as sessões sobrevivem a
reinícios do servidor, e cada relatório emitido fica registrado com o
hash SHA-256 do PDF, para conferência posterior da cópia anexada ao SEI.

O caminho do banco é configurável por DATA_CROSSING_DB.
Padrão: data-crossing/data/licita_facil.db
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

_PADRAO = Path(__file__).resolve().parents[2] / "data" / "licita_facil.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessoes (
    processo_id   TEXT PRIMARY KEY,
    dados         TEXT NOT NULL,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relatorios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id   TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    total_achados INTEGER NOT NULL,
    com_parecer   INTEGER NOT NULL,
    emitido_em    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relatorios_processo ON relatorios (processo_id);
"""


def _caminho() -> Path:
    return Path(os.environ.get("DATA_CROSSING_DB", _PADRAO))


@contextmanager
def _conexao():
    caminho = _caminho()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def obter_sessao(processo_id: str) -> Optional[dict]:
    with _conexao() as conn:
        linha = conn.execute(
            "SELECT dados FROM sessoes WHERE processo_id = ?", (processo_id,)
        ).fetchone()
    return json.loads(linha[0]) if linha else None


def salvar_sessao(processo_id: str, dados: dict) -> None:
    agora = _agora()
    with _conexao() as conn:
        conn.execute(
            """
            INSERT INTO sessoes (processo_id, dados, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(processo_id) DO UPDATE SET
                dados = excluded.dados,
                atualizado_em = excluded.atualizado_em
            """,
            (processo_id, json.dumps(dados, ensure_ascii=False), agora, agora),
        )


def remover_sessao(processo_id: str) -> None:
    with _conexao() as conn:
        conn.execute("DELETE FROM sessoes WHERE processo_id = ?", (processo_id,))


def registrar_relatorio(processo_id: str, sha256: str, total_achados: int, com_parecer: bool) -> None:
    with _conexao() as conn:
        conn.execute(
            """
            INSERT INTO relatorios (processo_id, sha256, total_achados, com_parecer, emitido_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (processo_id, sha256, total_achados, int(com_parecer), _agora()),
        )


def listar_relatorios(processo_id: str) -> list[dict]:
    with _conexao() as conn:
        linhas = conn.execute(
            """
            SELECT sha256, total_achados, com_parecer, emitido_em
            FROM relatorios WHERE processo_id = ? ORDER BY id
            """,
            (processo_id,),
        ).fetchall()
    return [
        {"sha256": s, "total_achados": t, "com_parecer": bool(c), "emitido_em": e}
        for s, t, c, e in linhas
    ]
