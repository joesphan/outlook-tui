# outlook-tui

An ad-free terminal mail client. IMAP, standard library only, one file of dependencies you don't have to install.

## Why this exists

The new Outlook for Windows renders an `Ad`-labelled row in the message list for free accounts, and that row is delivered service-side — no client-side patch removes it. That research is in [joesphan/new-outlook-abliterated](https://github.com/joesphan/new-outlook-abliterated).

This client takes the other road: it reads mail over IMAP directly, so there is no ad slot to remove, no upsell row, no telemetry and no WebView. What you get is a mailbox and nothing else.

## Status

Verified on this machine:

| Check | Result |
|---|---|
| `python tests/smoke.py` against a local mock IMAP server | **24/24 pass** |
| `python tests/setup_test.py` (account wizard) | **14/14 pass** |
| Handshake with `outlook.office365.com` (TLS 1.3) | works, `STATE=NONAUTH` |
| Handshake with `imap-mail.outlook.com` | works |
| Handshake with `imap.gmail.com` | works |
| Basic-auth refusal is detected and explained | works on all three |
| Fetching a real mailbox | **not yet** — needs an OAuth client ID you own (§Auth) |

That last row is deliberate honesty: the read path is exercised end to end against the mock, and the only thing standing between it and your inbox is an app registration.

## Requirements

Python 3.10+. Nothing else. No `pip install`.

## Auth

### Microsoft (outlook.com, hotmail.com, M365)

The service advertises `AUTH=XOAUTH2 LOGINDISABLED`, so passwords and app passwords are refused outright. You need an OAuth client ID:

1. <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations** → **New registration**
2. Name it anything. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**
3. **Register**. Copy the **Application (client) ID**
4. **Authentication** → **Allow public client flows** → **Yes** → **Save**
5. No client secret, no redirect URI needed — device-code flow uses neither

Put that client ID in the config. On first run the client prints a code and a URL; sign in once in a browser and the refresh token is cached under `%LOCALAPPDATA%\outlook-tui\`, so it doesn't ask again.

**Why not reuse the Outlook app's own client ID?** That identity belongs to Microsoft's application registration and its redirect is package-scoped (`ms-appx-web://…/`). A third-party client presenting it would be impersonating Microsoft's app. This client signs in as your registration, and the token is issued to you.

### Google (gmail.com, Google Workspace)

Gmail still advertises `AUTH=PLAIN`:

1. <https://myaccount.google.com/apppasswords> (requires 2-Step Verification)
2. Create one — the wizard asks for it when you add the account

## Adding an account

Nothing needs to be configured by hand. The wizard runs from inside the client:

- **first launch with no accounts** — it starts automatically
- **`python -m outlook_tui --setup`** — any time
- **press `a`** in the message list — adds an account, then reopens the new one

It asks for the address, works out the provider from the domain, and prompts only for what that provider needs:

| Address | Asked for |
|---|---|
| `@outlook.com`, `@hotmail.com`, `@live.com` | application (client) ID, once |
| `@gmail.com`, `@googlemail.com` | Google app password |
| anything else | IMAP host, port, password |

Accounts are stored at `%LOCALAPPDATA%\outlook-tui\config.json`. Editing it by hand still works if you prefer:

```json
{
  "accounts": [
    {
      "name": "personal",
      "provider": "microsoft",
      "host": "outlook.office365.com",
      "user": "you@outlook.com",
      "client_id": "00000000-0000-0000-0000-000000000000",
      "tenant": "consumers"
    }
  ]
}
```

`tenant` is `common` for personal + work, `consumers` for personal only, `organizations` for work only.

## Run

```bash
python -m outlook_tui                       # first account, interactive
python -m outlook_tui --setup               # add another account
python -m outlook_tui --account gmail       # pick by name or address
python -m outlook_tui --once                # render one screen, exit (scriptable)
python -m outlook_tui --mock --once         # canned mailbox, no credentials, no network
python -m outlook_tui --no-browser          # cached token only, never prompt
```

| Key | Action |
|---|---|
| `j` / `↓` | next message |
| `k` / `↑` | previous message |
| `g` / `G` | first / last |
| `Enter` | open in reader |
| `Esc` | back to list |
| `Tab` / `→` | next folder |
| `r` | reload folder |
| `a` | add an account |
| `q` | quit |

## Design notes

- **Read-only by design**: folders are opened with `EXAMINE`, so nothing is marked read and no server state changes. Sending is not implemented, which is also why this cannot damage a mailbox.
- **Mailbox names are quoted** before `SELECT`; imaplib does not do it, and `Sent Items` / `[Gmail]/All Mail` otherwise parse as extra tokens.
- **Newest first**: IMAP returns UIDs ascending, so the list reverses them after taking the tail.
- **Mock server included** (`outlook_tui/mock_imap.py`): a deliberately small IMAP implementation that speaks only the commands the client issues, so the whole read path can be tested without an account.

## Limitations

- Read-only: no compose, reply, delete, move, or flag changes.
- No attachments, no HTML rendering (plain text body only), no search UI.
- Folder names are handled as returned; non-ASCII names would need IMAP modified UTF-7, which is not implemented.
- One account per invocation.

## License

MIT — see [LICENSE](LICENSE).
