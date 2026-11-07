"""
Configuração via variáveis de ambiente.

Nenhuma credencial fica no código. Em produção (LXC), as variáveis vêm de um
arquivo `.env` na raiz do projeto (fora do git, permissão 600) ou do systemd
(`EnvironmentFile=`). Veja `.env.example`.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carrega KEY=VALUE de um .env sem sobrescrever o que já está no ambiente."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Variável de ambiente {name} não definida. "
            f"Crie {ROOT / '.env'} a partir de .env.example."
        )
    return value


def brudam_credentials() -> tuple[str, str]:
    return require("BRUDAM_USER"), require("BRUDAM_PASS")


def db_config() -> dict:
    return {
        "host": require("DB_HOST"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "dbname": os.environ.get("DB_NAME", "ares_bi"),
        "user": require("DB_USER"),
        "password": require("DB_PASSWORD"),
    }
