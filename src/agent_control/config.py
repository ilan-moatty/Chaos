from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from agent_control import __version__


def _env_flag(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ChaosSettings:
    db_path: str = "agent-control.db"
    host: str = "127.0.0.1"
    port: int = 8000
    environment: str = "development"
    api_token: Optional[str] = None
    operator_header: str = "X-Chaos-Operator"
    request_logging_enabled: bool = False
    app_version: str = __version__

    @property
    def api_auth_enabled(self) -> bool:
        return bool(self.api_token)

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "ChaosSettings":
        env = dict(environ or os.environ)
        return cls(
            db_path=env.get("CHAOS_DB_PATH", "agent-control.db"),
            host=env.get("CHAOS_HOST", "127.0.0.1"),
            port=int(env.get("CHAOS_PORT", "8000")),
            environment=env.get("CHAOS_ENV", "development"),
            api_token=env.get("CHAOS_API_TOKEN") or None,
            operator_header=env.get("CHAOS_OPERATOR_HEADER", "X-Chaos-Operator"),
            request_logging_enabled=_env_flag(env.get("CHAOS_REQUEST_LOGGING"), False),
        )
