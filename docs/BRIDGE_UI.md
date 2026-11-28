# BRIDGE operations dashboard

The default interface restores a dense six-panel operations grid: watcher/service, execution history, ECLIPSE task, recovery/health, provider links, and controls. The animated request/result bridge and title highlight remain separate from job progress. No simulated percentages or random telemetry are shown.

The watcher is identified by a real process argument. A stopped managed service or stale supervisor heartbeat does not mark a separate live watcher offline. Queue counts and recent requests come from a read-only SQLite snapshot; the legacy JSON file is a labeled fallback. Missing process visibility means CHECK, not a fabricated offline verdict. Provider links show configuration, not unverified network connectivity. Task details show only explicitly linked metadata.

The screen measures the actual TTY every redraw, uses bounded cell widths, absolute row addressing and guarded autowrap, and restores the alternate screen and terminal on exit. Rotation, split-screen, font-size changes, and continuous window resizing are supported.

- Close and reopen an existing monitor to load an update.
- Press 1 for Overview, 2 for History, 3 for Task, 4 for Health, or 5 for Links. Tab changes views. J/K scroll the history view. Small terminals keep details reachable through these views.
- Press Q, Esc, or Ctrl+C to close the monitor. Closing the view does not stop the watcher.
- Use BRIDGE menu for the existing service controls; the monitor does not start or restart services.
- BRIDGE_UI_REDUCED_MOTION=1 disables decorative motion and slows refresh. NO_COLOR=1 selects monochrome. BRIDGE_UI_STYLE=classic selects the earlier dashboard.

Design references: btop (https://github.com/aristocratos/btop), Textual layout (https://textual.textualize.io/guide/layout/), and Rich Live (https://rich.readthedocs.io/en/stable/live.html). The implementation uses the existing Python standard library and adds no runtime packages.
