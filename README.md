# TGFlow

TGFlow is a cross-platform desktop application for operator-controlled Telegram workflow automation. It combines a PyQt6 interface with an async Pyrogram/MTProto backend, local-first storage, recipient checks, dry-run mode, and detailed execution logs.

The repository is kept as a portfolio example of Python desktop engineering, async queue orchestration, Telegram client automation, and safety-first operator tooling.

## Highlights

- Multi-account orchestration through async worker queues.
- PyQt6 desktop UI with account management, campaign controls, and chat selection.
- MTProto integration via Pyrogram for Telegram dialogs, groups, and channels.
- Dry-run mode and recipient preflight checks before any real send action.
- Adaptive rate limiting, randomized delays, and FloodWait handling.
- HTML-to-MarkdownV2 message preparation and media optimization.
- Local-only user data: sessions, templates, and logs stay on the operator machine.
- Unit tests for core flows; live Telegram tests are opt-in and disabled by default.
- PyInstaller specs for macOS and Windows desktop builds.

## Architecture

```text
PyQt6 UI
  -> campaign/account state
  -> async BroadcastManager
  -> per-account worker pool
  -> Pyrogram clients
  -> local logs and operator-visible results
```

Core design decisions:

- The UI never blocks on network work; long-running Telegram operations run in async workers.
- Accounts are treated as resources in a pool. If one account is rate-limited or unavailable, work can be paused or moved without losing task state.
- Risky actions are explicit. Operators can inspect recipients and run a dry-run before a real campaign.
- Runtime artifacts such as sessions, logs, and templates are stored outside the repository and ignored by Git.

## Repository Structure

```text
main.py                 # application entry point
app/                    # UI and application modules
scripts/                # local message templates, ignored in runtime setups
tests/                  # unit and opt-in live tests
tgflow.spec             # macOS PyInstaller build
tgflow_win.spec         # Windows PyInstaller build
requirements.txt        # Python dependencies
```

## Quick Start

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Testing

Unit tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Live Telegram integration tests require real accounts/sessions and are disabled by default:

```bash
TGFLOW_RUN_LIVE_TESTS=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Build

```bash
pyinstaller tgflow.spec       # macOS
pyinstaller tgflow_win.spec   # Windows
```

The packaged `.app` / `.exe` is written to `dist/`.

## Local Data

Runtime data is stored in the user's application directory rather than in the repository:

- macOS: `~/Library/Application Support/TGFlow`
- Windows: `%APPDATA%\TGFlow`

Typical runtime files:

- `accounts.json` - saved account metadata
- `broadcast_logs/` - execution reports
- `scripts/` - local message templates
- `sessions/` - Pyrogram session files

These paths are excluded from version control.

## Responsible Use

TGFlow is an operator tool. It is designed around explicit setup, local ownership, preflight checks, logs, and manual responsibility for Telegram rules and recipient consent.

## License

All rights reserved. Portfolio review and educational reading are welcome; reuse requires written permission.
