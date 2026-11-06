"""In-app account setup — the "Add account" flow.

Everything is asked here: address, provider detection, credential, and the
Microsoft application ID. No config file editing.

One external step is unavoidable for Microsoft accounts: third-party clients
cannot sign in as Microsoft's own application, so the device-code flow needs an
application ID that belongs to you. The wizard explains it and takes the value;
enter it once and every later run is silent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import (
    Account,
    default_config_path,
    load_config,
    read_config_file,
    resolve_config_path,
    write_config,
)

PROVIDER_BY_DOMAIN = {
    "outlook.com": "microsoft",
    "hotmail.com": "microsoft",
    "live.com": "microsoft",
    "msn.com": "microsoft",
    "gmail.com": "google",
    "googlemail.com": "google",
}
DEFAULT_HOST = {"microsoft": "outlook.office365.com", "google": "imap.gmail.com"}
CONSUMER_DOMAINS = {"outlook.com", "hotmail.com", "live.com", "msn.com"}

REGISTRATION_HELP = """
  Microsoft accounts need a one-time application ID (about 3 minutes, free):

    1. https://portal.azure.com  ->  Microsoft Entra ID  ->  App registrations
    2. New registration
       Name: anything
       Account types: Accounts in any organizational directory and personal
                      Microsoft accounts
    3. Register, then copy "Application (client) ID"
    4. Authentication -> Allow public client flows -> Yes -> Save

  This is not a Microsoft account password: it identifies your own copy of this
  client. No secret and no redirect URI are needed.
"""


def guess_provider(email: str) -> str:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return PROVIDER_BY_DOMAIN.get(domain, "imap")


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or (default or "")


def _ask_secret(prompt: str) -> str:
    if sys.stdin is not None and sys.stdin.isatty():
        import getpass

        return getpass.getpass(f"  {prompt}: ").strip()
    try:
        return input(f"  {prompt}: ").strip()
    except EOFError:
        return ""


def wizard(explicit: str | None = None) -> list[Account]:
    if explicit:
        path = Path(explicit)
        existing = read_config_file(path, missing_ok=True)
    else:
        path = resolve_config_path() or default_config_path()
        existing = load_config(missing_ok=True)

    print()
    print("  Add an account")
    print("  " + "-" * 64)
    if existing:
        print("  configured: " + ", ".join(f"{a.name} ({a.user})" for a in existing))
    else:
        print("  no accounts configured yet")
    print()

    email = _ask("Email address")
    if not email or "@" not in email:
        raise ValueError("an email address is required")

    provider = guess_provider(email)
    provider = _ask(f"Provider (microsoft/google/imap)", provider).lower()
    if provider not in {"microsoft", "google", "imap"}:
        raise ValueError(f"unknown provider {provider!r}")

    domain = email.rsplit("@", 1)[-1].lower()
    tenant = "consumers" if domain in CONSUMER_DOMAINS else "organizations"
    host = DEFAULT_HOST.get(provider, "")
    port = 993
    client_id: str | None = None
    app_password: str | None = None

    if provider == "microsoft":
        host = _ask("IMAP host", host)
        tenant = _ask("Tenant (consumers/organizations/common)", tenant)
        client_id = os.environ.get("OUTLOOK_TUI_CLIENT_ID") or next(
            (a.client_id for a in existing if a.client_id), None
        )
        if not client_id:
            print(REGISTRATION_HELP)
            client_id = _ask("Application (client) ID")
        else:
            print(f"  using application ID already configured: {client_id[:8]}…")
        if not client_id:
            raise ValueError("a Microsoft application (client) ID is required")
    elif provider == "google":
        host = _ask("IMAP host", host or "imap.gmail.com")
        print()
        print("  Create an app password at https://myaccount.google.com/apppasswords")
        print("  (requires 2-Step Verification). It is stored locally and never sent anywhere else.")
        print()
        app_password = _ask_secret("App password")
        if not app_password:
            raise ValueError("an app password is required")
    else:
        host = _ask("IMAP host")
        port = int(_ask("Port", "993"))
        print()
        app_password = _ask_secret("Password")
        if not app_password:
            raise ValueError("a password is required")

    name = _ask("Name for this account", email.split("@")[0])

    account = Account(
        name=name,
        provider=provider,
        host=host,
        user=email,
        port=port,
        client_id=client_id,
        tenant=tenant,
        app_password=app_password,
    )

    merged = [a for a in existing if a.user.lower() != email.lower()] + [account]
    write_config(merged, path)

    print()
    print(f"  saved {len(merged)} account(s) to {path}")
    if provider == "microsoft":
        print("  the first run will show a code to approve in a browser")
    print("  start it with:  python -m outlook_tui")
    print()
    return merged
