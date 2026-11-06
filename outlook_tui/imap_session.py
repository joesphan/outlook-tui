"""Minimal IMAP client used by the TUI.

Stdlib only. Supports:
  - Microsoft (outlook.com / M365): SASL XOAUTH2, because the service advertises
    LOGINDISABLED and no longer accepts basic auth or app passwords.
  - Google: AUTH=PLAIN via app password, or XOAUTH2 if a token is supplied.
"""

from __future__ import annotations

import imaplib
import re
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime


class AuthError(RuntimeError):
    pass


@dataclass
class MessageSummary:
    uid: str
    subject: str
    sender: str
    date: str
    unread: bool


def _decode(value: str | bytes | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _strip_tags(subject: str) -> str:
    # OWA prefixes the in-list ad row with an "Ad" label; a real message never has it.
    return re.sub(r"^\s*\[?ad\]?\s*", "", subject, flags=re.IGNORECASE)


class ImapSession:
    def __init__(
        self,
        host: str,
        user: str,
        *,
        port: int = 993,
        use_tls: bool = True,
        token: str | None = None,
        password: str | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.use_tls = use_tls
        self.token = token
        self.password = password
        self._imap: imaplib.IMAP4 | None = None
        self.capabilities: list[str] = []

    # -- connection ---------------------------------------------------------
    def connect(self) -> None:
        if self.use_tls:
            ctx = ssl.create_default_context()
            self._imap = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=ctx)
        else:
            self._imap = imaplib.IMAP4(self.host, self.port)

        self.capabilities = [str(c) for c in self._imap.capabilities]
        self._authenticate()

    def _authenticate(self) -> None:
        assert self._imap is not None
        if self.token:
            try:
                self._imap.authenticate("XOAUTH2", self._xoauth2)
            except imaplib.IMAP4.error as exc:
                raise AuthError(f"XOAUTH2 rejected for {self.user}: {exc}") from exc
            return

        if self.password:
            if "LOGINDISABLED" in self.capabilities:
                raise AuthError(
                    "server advertises LOGINDISABLED: basic auth is off, an OAuth token is required"
                )
            try:
                self._imap.login(self.user, self.password)
            except imaplib.IMAP4.error as exc:
                raise AuthError(f"login rejected for {self.user}: {exc}") from exc
            return

        raise AuthError("no credential supplied (need token or password)")

    def _xoauth2(self, _challenge: bytes | None = None) -> bytes:
        return f"user={self.user}\x01auth=Bearer {self.token}\x01\x01".encode()

    def close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # -- operations ---------------------------------------------------------
    def folders(self) -> list[str]:
        assert self._imap is not None
        status, data = self._imap.list()
        if status != "OK":
            return []
        out: list[str] = []
        for raw in data or []:
            if raw is None:
                continue
            line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            # imaplib hands back: (\HasNoChildren) "/" "Sent Items"
            match = re.match(r'^\([^)]*\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+?)\s*$', line)
            if not match:
                continue
            name = match.group("name")
            if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            if name:
                out.append(name)
        return out or ["INBOX"]

    def select(self, mailbox: str = "INBOX") -> int:
        assert self._imap is not None
        # imaplib does not quote arguments; names with spaces (Sent Items,
        # [Gmail]/All Mail) must be quoted or the server sees extra tokens.
        arg = mailbox
        if any(ch in mailbox for ch in ' "()[]'):
            arg = '"' + mailbox.replace('"', '\\"') + '"'
        status, data = self._imap.select(arg, readonly=True)
        if status != "OK":
            raise RuntimeError(f"cannot select {mailbox}: {data}")
        try:
            return int(data[0])
        except (TypeError, ValueError, IndexError):
            return 0

    def messages(self, limit: int = 50) -> list[MessageSummary]:
        assert self._imap is not None
        status, data = self._imap.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        uids = uids[-limit:][::-1]

        out: list[MessageSummary] = []
        for uid in uids:
            fields = "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"
            status, parts = self._imap.uid("fetch", uid, fields)
            if status != "OK" or not parts:
                continue
            flags = b""
            header = b""
            for part in parts:
                if isinstance(part, tuple):
                    flags += part[0]
                    header += part[1]
            text = header.decode(errors="replace")
            subject = _decode(_header_value(text, "Subject"))
            sender = _decode(_header_value(text, "From"))
            date_raw = _header_value(text, "Date")
            out.append(
                MessageSummary(
                    uid=uid.decode(),
                    subject=_strip_tags(subject),
                    sender=sender,
                    date=_short_date(date_raw),
                    unread=b"\\Seen" not in flags,
                )
            )
        return out

    def body(self, uid: str) -> str:
        assert self._imap is not None
        status, parts = self._imap.uid("fetch", uid, "(BODY.PEEK[TEXT])")
        if status != "OK" or not parts:
            return ""
        chunks = [p[1] for p in parts if isinstance(p, tuple)]
        raw = b"".join(chunks).decode(errors="replace")
        return raw.strip()


def _header_value(block: str, name: str) -> str:
    for line in block.splitlines():
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _short_date(raw: str) -> str:
    try:
        return parsedate_to_datetime(raw).strftime("%m-%d %H:%M")
    except Exception:
        return raw[:16]
