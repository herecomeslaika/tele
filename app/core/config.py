"""A2A_min_v1 Gateway Configuration Loader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class ProviderEntry:
    provider_type: str
    name: str
    endpoint: str
    model: str
    api_key: str = ""
    timeout: float = 60.0
    max_tokens: int = 2048
    temperature: float = 0.7
    capabilities: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)


@dataclass
class GatewayConfig:
    protocol_version: str = "v1"
    protocol_compatibility: bool = True

    host: str = "0.0.0.0"
    port: int = 8000
    strategy: str = "priority"

    first_token_timeout: float = 30.0
    token_interval_timeout: float = 15.0
    total_task_timeout: float = 120.0
    provider_response_timeout: float = 60.0

    heartbeat_interval: float = 15.0

    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    retry_backoff_factor: float = 2.0

    max_queue_length: int = 1000
    send_rate_limit: int = 100

    security_enabled: bool = True
    require_agent_id: bool = True
    max_input_length: int = 10000
    max_output_length: int = 50000

    log_level: str = "INFO"
    log_format: str = "json"

    metrics_enabled: bool = True
    audit_enabled: bool = True
    audit_log_dir: str = "evidence/audit"

    providers: list[ProviderEntry] = field(default_factory=list)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    v = os.getenv(key)
    return int(v) if v else default


def _env_float(key: str, default: float = 0.0) -> float:
    v = os.getenv(key)
    return float(v) if v else default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "").lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return default


def _parse_list(val: str) -> list[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


def load_config(env_file: Optional[str] = None) -> GatewayConfig:
    """Load gateway configuration from environment and .env file."""
    if env_file:
        load_dotenv(env_file)
    else:
        # Try to find .env in standard locations
        for candidate in ("config/.env", ".env"):
            if Path(candidate).exists():
                load_dotenv(candidate)
                break

    config = GatewayConfig(
        protocol_version=_env("PROTOCOL_VERSION", "v1"),
        protocol_compatibility=_env_bool("PROTOCOL_COMPATIBILITY", True),
        host=_env("GATEWAY_HOST", "0.0.0.0"),
        port=_env_int("GATEWAY_PORT", 8000),
        strategy=_env("GATEWAY_STRATEGY", "priority"),
        first_token_timeout=_env_float("FIRST_TOKEN_TIMEOUT", 30.0),
        token_interval_timeout=_env_float("TOKEN_INTERVAL_TIMEOUT", 15.0),
        total_task_timeout=_env_float("TOTAL_TASK_TIMEOUT", 120.0),
        provider_response_timeout=_env_float("PROVIDER_RESPONSE_TIMEOUT", 60.0),
        heartbeat_interval=_env_float("HEARTBEAT_INTERVAL", 15.0),
        max_retries=_env_int("MAX_RETRIES", 3),
        retry_base_delay=_env_float("RETRY_BASE_DELAY", 1.0),
        retry_max_delay=_env_float("RETRY_MAX_DELAY", 30.0),
        retry_backoff_factor=_env_float("RETRY_BACKOFF_FACTOR", 2.0),
        max_queue_length=_env_int("MAX_QUEUE_LENGTH", 1000),
        send_rate_limit=_env_int("SEND_RATE_LIMIT", 100),
        security_enabled=_env_bool("SECURITY_ENABLED", True),
        require_agent_id=_env_bool("REQUIRE_AGENT_ID", True),
        max_input_length=_env_int("MAX_INPUT_LENGTH", 10000),
        max_output_length=_env_int("MAX_OUTPUT_LENGTH", 50000),
        log_level=_env("LOG_LEVEL", "INFO"),
        log_format=_env("LOG_FORMAT", "json"),
        metrics_enabled=_env_bool("METRICS_ENABLED", True),
        audit_enabled=_env_bool("AUDIT_ENABLED", True),
        audit_log_dir=_env("AUDIT_LOG_DIR", "evidence/audit"),
    )

    # Load providers
    for i in range(1, 10):
        prefix = f"PROVIDER{i}_"
        ptype = _env(f"{prefix}TYPE")
        if not ptype:
            break
        config.providers.append(ProviderEntry(
            provider_type=ptype,
            name=_env(f"{prefix}NAME", f"provider_{i}"),
            endpoint=_env(f"{prefix}ENDPOINT", ""),
            model=_env(f"{prefix}MODEL", ""),
            api_key=_env(f"{prefix}API_KEY", ""),
            timeout=_env_float(f"{prefix}TIMEOUT", 60.0),
            max_tokens=_env_int(f"{prefix}MAX_TOKENS", 2048),
            temperature=_env_float(f"{prefix}TEMPERATURE", 0.7),
            capabilities=_parse_list(_env(f"{prefix}CAPABILITIES", "")),
            task_types=_parse_list(_env(f"{prefix}TASK_TYPES", "")),
        ))

    return config


def validate_config(config: GatewayConfig) -> list[str]:
    """Validate configuration and return list of error messages."""
    errors: list[str] = []

    if not config.providers:
        errors.append("No providers configured. Set PROVIDER1_TYPE, PROVIDER1_ENDPOINT, etc.")

    for p in config.providers:
        if not p.endpoint:
            errors.append(f"Provider '{p.name}' missing endpoint")
        if not p.model:
            errors.append(f"Provider '{p.name}' missing model")

    if config.strategy not in ("priority", "hash", "round_robin", "model_name", "task_type", "capability", "runtime"):
        errors.append(f"Unknown routing strategy: {config.strategy}")

    if config.max_retries < 0:
        errors.append("MAX_RETRIES must be >= 0")

    if config.max_queue_length < 1:
        errors.append("MAX_QUEUE_LENGTH must be >= 1")

    return errors