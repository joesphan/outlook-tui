"""Entry point: python -m outlook_tui [--config PATH] [--account NAME] [--once] [--mock] [--setup]"""

from __future__ import annotations

import argparse
import sys

from . import ui
from .auth import DeviceCodeAuth
from .config import Account, load_config
from .imap_session import AuthError, ImapSession
from .setup import wizard


def build_session(account: Account, *, interactive: bool) -> ImapSession:
    if account.provider == "microsoft" or account.client_id:
        if not account.client_id:
            raise AuthError(
                f"{account.user}: a client_id is required for Microsoft accounts "
                "(app passwords are refused: the server advertises LOGINDISABLED)"
            )
        token = DeviceCodeAuth(account.client_id, account.user, account.tenant).acquire(
            interactive=interactive
        )
        session = ImapSession(account.host, account.user, port=account.port, token=token)
    else:
        if not account.app_password:
            raise AuthError(f"{account.user}: app_password is required")
        session = ImapSession(
            account.host, account.user, port=account.port, password=account.app_password
        )
    session.connect()
    return session


def pick_account(accounts: list[Account], selector: str | None, *, last: bool = False) -> Account:
    if not accounts:
        raise ValueError("no accounts configured")
    if selector:
        wanted = selector.lower()
        matches = [a for a in accounts if wanted in (a.name.lower(), a.user.lower())]
        if not matches:
            raise ValueError(f"no account matching {selector!r}")
        return matches[0]
    return accounts[-1] if last else accounts[0]


def load_accounts(config: str | None) -> list[Account]:
    """Load accounts, running the setup wizard first if nothing is configured."""
    try:
        return load_config(config)
    except FileNotFoundError:
        print("No accounts configured yet.", file=sys.stderr)
        return wizard(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outlook_tui",
        description="Ad-free terminal mail client (IMAP). No ad slot, no upsell row.",
    )
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--account", help="account name or address to open")
    parser.add_argument("--setup", action="store_true", help="add or replace an account, then exit")
    parser.add_argument("--once", action="store_true", help="render one screen and exit")
    parser.add_argument("--mock", action="store_true", help="run against the built-in mock mailbox")
    parser.add_argument(
        "--no-browser", action="store_true", help="use only a cached token; never start sign-in"
    )
    args = parser.parse_args(argv)

    if args.setup:
        try:
            wizard(args.config)
        except (ValueError, EOFError) as exc:
            print(f"setup: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.mock:
        from .mock_imap import MockImapServer

        server = MockImapServer().start()
        session = ImapSession(
            server.host, "mock@local", port=server.port, use_tls=False, password="mock"
        )
        try:
            session.connect()
            if args.once:
                print(ui.render_once(session, "mock@local"))
                return 0
            return ui.run(session, "mock@local")
        finally:
            session.close()
            server.stop()

    try:
        accounts = load_accounts(args.config)
    except ValueError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    try:
        account = pick_account(accounts, args.account, last=True)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    while True:
        try:
            session = build_session(account, interactive=not args.no_browser)
        except AuthError as exc:
            print(f"auth: {exc}", file=sys.stderr)
            return 3
        except (OSError, RuntimeError) as exc:
            print(f"connect: {exc}", file=sys.stderr)
            return 4

        try:
            if args.once:
                print(ui.render_once(session, account.user))
                return 0
            code = ui.run(session, account.user)
        except KeyboardInterrupt:
            return 130
        finally:
            session.close()

        if code != 2:
            return code

        # "a" was pressed: add an account, then reopen the one just added.
        try:
            accounts = wizard(args.config)
            account = pick_account(accounts, None, last=True)
        except (ValueError, EOFError) as exc:
            print(f"setup: {exc}", file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
