"""End-to-end smoke test against the built-in mock mailbox.

Run: python tests/smoke.py
Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from outlook_tui import ui
from outlook_tui.imap_session import ImapSession
from outlook_tui.mock_imap import MockImapServer

CHECKS: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    CHECKS.append((label, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + label)


def main() -> int:
    with MockImapServer() as server:
        session = ImapSession(
            server.host, "mock@local", port=server.port, use_tls=False, password="mock"
        )
        session.connect()
        check("connected and authenticated", session.capabilities != [])
        check("CAPABILITY advertises AUTH=PLAIN", "AUTH=PLAIN" in session.capabilities)

        folders = session.folders()
        check("folders parsed", "INBOX" in folders)
        check("three folders listed", len(folders) == 3)

        count = session.select("INBOX")
        check("SELECT reports 4 messages", count == 4)

        messages = session.messages()
        check("4 summaries fetched", len(messages) == 4)
        check("subject decoded", messages[0].subject.startswith("Payroll is late"))
        check("sender decoded", "Gusto" in messages[0].sender)
        check("date shortened", messages[0].date.startswith("11-06"))

        body = session.body(messages[0].uid)
        check("body fetched", "Run your payroll today" in body)

        frame = ui.render_once(session, "mock@local")
        check("frame renders subject", "Payroll is late" in frame)
        check("frame renders folders pane", "FOLDERS" in frame)
        check("frame has no ad row", "[Ad]" not in frame and "Upgrade Your Account" not in frame)

        # ---- interactive key handling (no terminal needed) ----
        state = ui.State("mock@local")
        state.folders = session.folders()
        ui._load_folder(session, state)
        ui.handle_key(state, session, "j")
        check("j moves selection down", state.selected == 1)
        ui.handle_key(state, session, "k")
        check("k moves selection back", state.selected == 0)
        ui.handle_key(state, session, "G")
        check("G jumps to last message", state.selected == len(state.messages) - 1)
        ui.handle_key(state, session, "g")
        check("g jumps to first message", state.selected == 0)

        quit_result = ui.handle_key(state, session, "enter")
        check("enter opens the reader", state.mode == "read" and quit_result)
        check("reader shows body", "Run your payroll today" in state.body)
        read_frame = "\n".join(ui.render(state, 112, 20))
        check("reader frame shows sender", "Gusto" in read_frame)

        ui.handle_key(state, session, "esc")
        check("esc returns to the list", state.mode == "list")
        ui.handle_key(state, session, "tab")
        check("tab switches folder", state.folder == "Sent Items")
        check("folder reload fetched its mail", len(state.messages) == 1)
        check("q requests exit", ui.handle_key(state, session, "q") is False)

        session.close()

    failed = [label for label, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"FAILED {len(failed)}/{len(CHECKS)}")
        return 1
    print(f"PASS {len(CHECKS)}/{len(CHECKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
