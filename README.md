# ECLIPSE Chat Bridge (`eclipse-chat-bridge`)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)]()

An automated, bidirectional bridge between **Google Docs**, **Android Termux**, and the **ECLIPSE local execution runtime**. 

It enables cloud-based LLM assistants (such as ChatGPT or Gemini in browser sessions) to safely submit local execution requests—such as project diagnostics, tests, and build checks—and receive verified execution results with real-time Android notifications and bidirectional Google Doc synchronization.

---

## 🏗 Architecture & Workflow

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Phone
    participant AI as ChatGPT / Cloud AI
    participant Doc as Google Doc (Sync Channel)
    participant Watcher as eclipse-chat-bridge (Daemon)
    participant Termux as Termux / Android System

    AI->>Doc: Appends <<<ECLIPSE_BRIDGE_REQUEST_V1>>> block
    loop Every 5 seconds
        Watcher->>Doc: Check revisionId (Docs API metadata)
    end
    Note over Watcher,Doc: Document updated! revisionId changed
    Watcher->>Doc: Fetch full document body & parse requests
    Watcher->>Watcher: Validate path, credentials & deduplicate request ID
    Watcher->>Watcher: Execute script / read file / inspect project
    Watcher->>Doc: Append <<<ECLIPSE_BRIDGE_RESPONSE_V1>>> block
    Watcher->>Termux: ADB focus assist + termux-clipboard-set
    Watcher->>Termux: termux-toast & termux-notification (High Priority)
    User->>AI: Pastes result from Termux clipboard (or AI reads from Doc)
```

---

## ✨ Features

- **Google Docs Revision Polling:** Monitors document edits via Google Docs API `revisionId` field projection (`fields=revisionId`). Checks take ~2.5s on average with tiny payloads (~150 bytes), preventing API quota exhaustion.
- **Automated Hands-Free Execution:** Default `--execution auto` mode processes verified diagnostic requests immediately without blocking for local CLI prompt confirmation.
- **Android Background Clipboard Assist:** Android 10+ (`SDK >= 29`) blocks background services from reading or writing to the clipboard. The bridge features an automated ADB focus-assist fallback to toggle Termux foreground activity for 0.35s, sets the clipboard, and returns focus back to Chrome seamlessly.
- **Dual Android Notifications:** Simultaneously displays an on-screen toast (`termux-toast`) and persistent Android system notification tray alert (`termux-notification`) with high priority.
- **Bidirectional Google Doc Sync:** Automatically formats and appends response blocks (`<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>`) directly back into the Google Doc, giving LLM assistants a direct return channel.
- **Idempotent & Safe Execution:**
  - Strict regex request ID verification (`^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$`).
  - Request deduplication and tamper detection via SHA-256 fingerprinting in `requests.json`.
  - Path confinement within allowed project directories.
  - Hardened credential exclusion (blocks access to `token.json`, `credentials.json`, `.env`, SSH keys).
  - Subprocess timeouts and output caps (maximum 24,000 characters).

---

## 📜 Protocol Specification

### 1. Request Format (`<<<ECLIPSE_BRIDGE_REQUEST_V1>>>`)
The cloud assistant appends a request block to the designated Google Doc:

```json
<<<ECLIPSE_BRIDGE_REQUEST_V1>>>
{
  "id": "signal_browser_capabilities_20261114_r1",
  "action": "run",
  "cwd": "/root/projects/chat-run-docs",
  "script": "python3 -m unittest -v tests/test_tripo.py",
  "timeout_seconds": 60
}
<<<END_ECLIPSE_BRIDGE_REQUEST_V1>>>
```

Supported actions:
- **`run`**: Executes a bash script in `cwd` with strict process isolation and timeout.
- **`read_file`**: Reads bounded lines from a target file (`path`, `start_line`, `line_count`).
- **`list_files`**: Lists non-hidden directory contents (`path`).
- **`read_result`** (staged): Retrieve a bounded byte range from a previous completed execution result. No shell execution.
- **`find_result`** (staged): Case-insensitive ASCII literal search in saved output, returning the matching offset and evidence excerpt.

### Retrieve previous diagnostic evidence (staged actions)

Both operations accept a prior request ID, not a filesystem path. The watcher
verifies that the ID is recorded as completed, that a matching completed
`run` receipt exists, and that its output file is in the bridge's own
results directory. No symlinks or hardlinks are followed. Output is capped
and each response carries the source SHA-256 fingerprint.

Read a saved range:

```json
{
  "id": "context_read_20261115_r1",
  "action": "read_result",
  "source_id": "previous_run_20261115_r1",
  "offset": 0,
  "max_bytes": 240
}
```

Search a saved result without knowing the error's byte offset:

```json
{
  "id": "context_find_20261115_r1",
  "action": "find_result",
  "source_id": "previous_run_20261115_r1",
  "query": "Traceback",
  "start_offset": 0,
  "max_bytes": 240
}
```

The reader automatically sizes JSON output for the tablet's existing
650-character Latest Diagnostic slot. Each action still requires a unique
request ID; source_id refers to the original completed run. For pagination,
reuse the returned next_offset, and for subsequent literal matches use
next_search_offset. Byte offsets refer to the original UTF-8 output file.

These actions do not change the Google Docs protocol, run tests, or modify
the provider browser. The new code is staged on an isolated branch and is
not live until separately activated.

### 2. Response Format (`<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>`)
The bridge automatically writes the receipt to the document and to the local state directory:

```json
<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>
{
  "id": "signal_browser_capabilities_20261114_r1",
  "result": {
    "status": "completed",
    "action": "run",
    "result": {
      "exit_code": 0,
      "timeout_or_output_limit": false,
      "output": "test_tripo_export (tests.test_tripo.TripoTests) ... ok\nRan 1 test in 0.042s\nOK\n",
      "truncated": false,
      "full_output_file": "/root/.local/state/eclipse-chat-bridge/results/signal_browser_capabilities_20261114_r1.raw"
    }
  }
}
<<<END_ECLIPSE_BRIDGE_RESPONSE_V1>>>
```

---

## Read-only project context snapshots (development feature)

The bridge can assemble source-screened, provenance-linked context into a **local
saved result**, while returning only a compact receipt through the existing
Google Docs Latest Diagnostic section:

```json
{
  "id": "context_snapshot_20261115_r1",
  "action": "context_snapshot",
  "project": "eclipse-chat-bridge",
  "goal": "diagnose response formatting and evidence retrieval"
}
```

The trusted watcher selects the project only from its workspace's immediate
subdirectories. It never accepts an arbitrary absolute filesystem root for this
action. Revision 11's Context Reader screens the source content; the Mode 7
Source Router ranks paths, and the graph engine parses only screened eligible
source text. Backups, archives, build outputs, and similar non-primary file
paths are filtered from graph and source evidence.

A snapshot's detailed JSON stays under the bridge's private results directory.
The Docs receipt includes its original request ID, source SHA-256, byte count,
graph edge count, and completion status. To retrieve the full contents, use
`read_result` with the snapshot request ID as `source_id`. To locate a
relevant path or symbol first, use `find_result` with the same source ID.

The reader's overview and search are **bounded and may be incomplete**.
Snapshots preserve truncation flags and evidence gaps. A graph relationship
is a best-effort static inference, not proof of runtime behavior. Context
Capture is explicitly marked `NOT_ATTACHED` until a capture result is
associated by an authorized caller; the snapshot action neither starts provider
capture nor modifies Context Reference Google Docs.

This feature never opens browser tabs, sends provider prompts, or applies game
code. The control Doc remains a small request/response channel.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Termux with `termux-api` installed (`pkg install termux-api`)
- Google OAuth credentials configured in `chat-run-docs`

### Installation
```bash
git clone https://github.com/rmtaa0916/eclipse-chat-bridge.git
cd eclipse-chat-bridge
pip install -r requirements.txt
```

### CLI Management (`bin/eclipse-bridge`)

A management script is included in `bin/eclipse-bridge`:

```bash
# Start the bridge daemon in background
./bin/eclipse-bridge start

# Check running status and request statistics
./bin/eclipse-bridge status

# View live execution logs
./bin/eclipse-bridge logs -f

# Run one single polling iteration and exit
./bin/eclipse-bridge once

# Run the unit test suite
./bin/eclipse-bridge test

# Stop the daemon
./bin/eclipse-bridge stop
```

---

## ⚙️ Configuration & Environment Variables

| Variable | Description | Default |
|---|---|---|
| `ECLIPSE_DOC_ID` | Default Google Doc ID to monitor | `1N_TYeHUTexHaU2eiZ40hMWsaNNl-GaZJ-6H1MxHPPYM` |
| `ECLIPSE_CORE_DIR` | Path to core Google Docs OAuth client | `/root/projects/chat-run-docs` |
| `ECLIPSE_BRIDGE_STATE` | State directory for tracking requests & logs | `/root/.local/state/eclipse-chat-bridge` |

---

## 🧪 Testing

The test suite validates request parsing, path validation, execution sandboxing, toast/notification triggers, and revision caching:

```bash
python3 -m unittest -v test_watch.py
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
