from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


FALSE_VALUES = {"0", "false", "no", "off"}
TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in FALSE_VALUES


def offline_enabled() -> bool:
    return env_bool("PROJECT_OFFLINE", True)


def configure_offline_environment() -> None:
    if not offline_enabled():
        return
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("KG_HF_OFFLINE", "1")


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("OFFLINE_ALLOWED_HOSTS", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _host_is_local_or_private(host: str) -> bool:
    clean = host.strip().lower().strip("[]")
    if not clean:
        return False
    if clean in {"localhost", "localhost.localdomain"}:
        return True
    if clean in _allowed_hosts():
        return True
    try:
        address = ipaddress.ip_address(clean)
    except ValueError:
        return "." not in clean or clean.endswith(".local")
    return address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified


def url_is_public_network(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname or ""
    return not _host_is_local_or_private(host)


def url_allowed_in_offline(url: str) -> bool:
    return not offline_enabled() or not url_is_public_network(url)
