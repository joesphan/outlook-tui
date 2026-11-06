"""Entry point: python -m outlook_tui [--config PATH] [--account NAME] [--once] [--mock]"""

from __future__ import annotations

import argparse
import sys

from . import ui
from .auth import DeviceCodeAuth
from .config import Account, load_config
from .imap_session import AuthError, ImapSession


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outlook_tui",
        description="Ad-free terminal mail client (IMAP). No ad slot, no upsell row.",
    )
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--account", help="account name or address to open")
    parser.add_argument("--once", action="store_true", help="render one screen and exit")
    parser.add_argument("--mock", action="store_true", help="run against the built-in mock mailbox")
    parser.add_argument(
        "--no-browser", action="store_true", help="use only a cached token; never start sign-in"
    )
    args = parser.parse_args(argv)

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
        accounts = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    if args.account:
        matches = [a for a in accounts if args.account.lower() in (a.name.lower(), a.user.lower())]
        if not matches:
            print(f"no account matching {args.account!r}", file=sys.stderr)
            return 2
        account = matches[0]
    else:
        account = accounts[0]

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
        return ui.run(session, account.user)
    except KeyboardInterrupt:
        return 130
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
