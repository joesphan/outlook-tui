"""ANSI TUI — no third-party dependency.

Windows: uses msvcrt for keys and enables VT processing on stdout.
POSIX: puts the terminal in raw mode for the duration.
"""

from __future__ import annotations

import os
import shutil
import sys

from .imap_session import MessageSummary

ESC = "\x1b"


def _enable_vt() -> None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def _size() -> tuple[int, int]:
    cols, lines = shutil.get_terminal_size(fallback=(110, 34))
    return max(60, cols), max(18, lines)


def _fit(text: str, width: int) -> str:
    if width <= 1:
        return ""
    text = text.replace("\t", " ")
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _pad(text: str, width: int) -> str:
    return _fit(text, width).ljust(width)


class State:
    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        self.folders: list[str] = ["INBOX"]
        self.folder_index = 0
        self.messages: list[MessageSummary] = []
        self.selected = 0
        self.mode = "list"
        self.body = ""
        self.status = ""
        self.pending: str | None = None

    @property
    def folder(self) -> str:
        return self.folders[self.folder_index]

    @property
    def current(self) -> MessageSummary | None:
        if 0 <= self.selected < len(self.messages):
            return self.messages[self.selected]
        return None


def render(state: State, width: int, height: int) -> list[str]:
    folder_w = 22 if width >= 100 else 18
    list_w = width - folder_w - 3
    left_title = " FOLDERS"
    right_title = f" {state.folder}  ({len(state.messages)})"

    title = f" Outlook TUI  ·  {state.account_name}"
    hint = "q quit  j/k move  enter open  tab folder  r reload  a add"
    head = _pad(title, width - len(hint)) + hint
    rule = "─" * width

    rows: list[str] = [head[:width], rule]

    if state.mode == "read" and state.current is not None:
        msg = state.current
        rows.append(_fit(f" {msg.subject}", width))
        rows.append(_fit(f" from {msg.sender}   {msg.date}", width))
        rows.append(rule)
        body_lines = state.body.splitlines() or [""]
        room = height - 5
        for line in body_lines[:room]:
            rows.append(" " + _fit(line, width - 1))
        return rows

    header = _pad(" " + left_title, folder_w) + " │ " + _pad(right_title, list_w)
    rows.append(header)
    rows.append("─" * folder_w + "─┼─" + "─" * list_w)

    visible = height - 5
    for index in range(visible):
        if index < len(state.folders):
            name = state.folders[index]
            marker = ">" if index == state.folder_index else " "
            left = _pad(f" {marker} {name}", folder_w)
        else:
            left = " " * folder_w

        if index < len(state.messages):
            msg = state.messages[index]
            cursor = ">" if index == state.selected else " "
            dot = "•" if msg.unread else " "
            subj_w = max(10, list_w - 42)
            right = (
                f" {cursor} {dot} "
                + _pad(msg.subject, subj_w)
                + " "
                + _pad(msg.sender[:18], 20)
                + " "
                + (msg.date[-11:].rjust(11) if msg.date else " " * 11)
            )
        else:
            right = ""
        rows.append(_pad(left, folder_w) + " │ " + _pad(right, list_w))

    rows.append("─" * width)
    status = state.status or "read-only: no flags are changed on the server"
    rows.append(_fit(" " + status, width))
    return rows


def _draw(lines: list[str], height: int) -> None:
    while len(lines) < height:
        lines.append("")
    out = [ESC + "[H"]
    for line in lines[: height - 1]:
        out.append(line + "\r\n")
    out.append(lines[height - 1])
    out.append(ESC + "[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(code, "")
        if ch == "\r":
            return "enter"
        if ch == "\t":
            return "tab"
        if ch == "\x1b":
            return "esc"
        if ch in ("\x08",):
            return "esc"
        return ch
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\t":
            return "tab"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _load_folder(session, state: State) -> None:
    session.select(state.folder)
    state.messages = session.messages()
    state.selected = 0
    state.status = f"{state.folder}: {len(state.messages)} messages"


def handle_key(state: State, session, key: str) -> bool:
    """Apply one keypress. Returns False when the UI should exit."""
    if key == "q" or (key == "esc" and state.mode == "list"):
        return False
    if key in ("j", "down"):
        if state.selected < len(state.messages) - 1:
            state.selected += 1
    elif key in ("k", "up"):
        if state.selected > 0:
            state.selected -= 1
    elif key == "g":
        state.selected = 0
    elif key == "G":
        state.selected = max(0, len(state.messages) - 1)
    elif key == "enter":
        msg = state.current
        if msg is not None:
            state.body = session.body(msg.uid)
            state.mode = "read"
    elif key in ("esc", "left"):
        state.mode = "list"
    elif key in ("tab", "right"):
        state.mode = "list"
        state.folder_index = (state.folder_index + 1) % len(state.folders)
        _load_folder(session, state)
    elif key == "r":
        _load_folder(session, state)
    elif key == "a":
        state.pending = "setup"
    return True


def run(session, account_name: str) -> int:
    _enable_vt()
    state = State(account_name)
    state.folders = session.folders() or ["INBOX"]
    state.folder_index = 0
    _load_folder(session, state)

    sys.stdout.write(ESC + "[?25l" + ESC + "[2J")
    try:
        while True:
            width, height = _size()
            _draw(render(state, width, height), height)
            if not handle_key(state, session, _read_key()):
                break
            if state.pending == "setup":
                return 2
    finally:
        sys.stdout.write(ESC + "[?25h" + ESC + "[2J" + ESC + "[H")
        sys.stdout.flush()
    return 0


def render_once(session, account_name: str) -> str:
    state = State(account_name)
    state.folders = session.folders() or ["INBOX"]
    _load_folder(session, state)
    width, height = _size()
    return "\n".join(render(state, width, height))
