"""All runtime settings come from environment variables (12-factor).

Local dev  -> export them in your shell:   export BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-5-5
Kubernetes -> ConfigMap sre-agent-config + Secrets sre-agent-aws / sre-agent-db / sre-agent-auth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    env: str
    aws_region: str
    model_id: str | None
    max_tokens: int
    guardrail_id: str | None
    guardrail_version: str
    postgres_host: str | None
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str | None
    kubectl_bin: str
    kubectl_context: str | None
    kubectl_timeout: int
    max_output_chars: int
    recursion_limit: int
    api_token: str | None
    log_level: str

    @property
    def postgres_uri(self) -> str | None:
        """Memory backend. None -> in-memory (local dev, tests)."""
        if not self.postgres_host:
            return None
        auth = quote(self.postgres_user, safe="")
        if self.postgres_password:
            auth += ":" + quote(self.postgres_password, safe="")
        return f"postgresql://{auth}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?sslmode=disable"


def load_settings() -> Settings:
    """Read settings at call time (not import time) so tests can override env."""
    return Settings(
        env=_env("AGENT_ENV", "dev"),
        aws_region=_env("AWS_REGION", "eu-central-1"),
        model_id=_env("BEDROCK_MODEL_ID"),
        max_tokens=int(_env("MAX_TOKENS", "4096")),
        guardrail_id=_env("BEDROCK_GUARDRAIL_ID"),
        guardrail_version=_env("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        postgres_host=_env("POSTGRES_HOST"),
        postgres_port=int(_env("POSTGRES_PORT", "5432")),
        postgres_db=_env("POSTGRES_DB", "sreagent"),
        postgres_user=_env("POSTGRES_USER", "sreagent"),
        postgres_password=_env("POSTGRES_PASSWORD"),
        kubectl_bin=_env("KUBECTL_BIN", "kubectl"),
        kubectl_context=_env("KUBECTL_CONTEXT"),
        kubectl_timeout=int(_env("KUBECTL_TIMEOUT", "30")),
        max_output_chars=int(_env("MAX_OUTPUT_CHARS", "12000")),
        recursion_limit=int(_env("RECURSION_LIMIT", "40")),
        api_token=_env("API_TOKEN"),
        log_level=_env("LOG_LEVEL", "INFO"),
    )
