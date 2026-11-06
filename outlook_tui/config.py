"""Config loading.

Lookup order: --config, $OUTLOOK_TUI_CONFIG, %LOCALAPPDATA%\\outlook-tui\\config.json,
./config.json.

A config is a JSON object with an "accounts" array. Two shapes are supported:

  microsoft:  { "provider": "microsoft", "host": "outlook.office365.com",
                "user": "...", "client_id": "...", "tenant": "common" }

  google:     { "provider": "google", "host": "imap.gmail.com",
                "user": "...", "app_password": "..." }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Account:
    name: str
    provider: str
    host: str
    user: str
    port: int = 993
    client_id: str | None = None
    tenant: str = "common"
    app_password: str | None = None

    @property
    def uses_oauth(self) -> bool:
        return self.provider == "microsoft" or bool(self.client_id)


def config_candidates(explicit: str | None = None) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    env = os.environ.get("OUTLOOK_TUI_CONFIG")
    if env:
        paths.append(Path(env))
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    paths.append(Path(base) / "outlook-tui" / "config.json")
    paths.append(Path.cwd() / "config.json")
    return paths


def load_config(explicit: str | None = None) -> list[Account]:
    for path in config_candidates(explicit):
        if path.is_file():
            blob = json.loads(path.read_text(encoding="utf-8"))
            break
    else:
        tried = ", ".join(str(p) for p in config_candidates(explicit))
        raise FileNotFoundError(f"no config found; tried: {tried}")

    raw_accounts = blob.get("accounts")
    if not isinstance(raw_accounts, list) or not raw_accounts:
        raise ValueError("config must contain a non-empty 'accounts' array")

    accounts: list[Account] = []
    for index, item in enumerate(raw_accounts, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"account #{index} is not an object")
        missing = [k for k in ("host", "user") if not item.get(k)]
        if missing:
            raise ValueError(f"account #{index} missing {', '.join(missing)}")
        provider = str(item.get("provider", "microsoft")).lower()
        if provider not in {"microsoft", "google", "imap"}:
            raise ValueError(f"account #{index}: unknown provider {provider!r}")
        accounts.append(
            Account(
                name=str(item.get("name") or item["user"]),
                provider=provider,
                host=str(item["host"]),
                user=str(item["user"]),
                port=int(item.get("port", 993)),
                client_id=(str(item["client_id"]).strip() if item.get("client_id") else None),
                tenant=str(item.get("tenant", "common")),
                app_password=(str(item["app_password"]) if item.get("app_password") else None),
            )
        )
    return accounts
