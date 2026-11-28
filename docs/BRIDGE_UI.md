# BRIDGE interface

The default interface uses a moving eclipse orbit, a subtle title shimmer, and a stable view of actual execution and service status. Motion is decorative and does not estimate job progress. History stays in place while reading.

The monitor measures the live terminal on every redraw. Rotation, split-screen, font-size changes, and repeated window resizing switch the layout automatically. The renderer reserves a row and column to avoid wrapping or scrolling at the bottom edge. Terminals without a TTY receive one static frame.

- Open the installed native `BRIDGE` launcher as usual. Close and reopen an already running monitor to load this interface update.
- Exit the monitor with any key; the background watcher continues running. Use `BRIDGE menu` for the existing service controls.
- Set `BRIDGE_UI_REDUCED_MOTION=1` for a still illustration and slower refresh.
- Set `NO_COLOR=1` for monochrome output.
- Set `BRIDGE_UI_STYLE=classic` to use the previous dashboard layout. Automatic cell-width fitting applies to the default eclipse layout.

The interface reads existing local state and cached service health. It does not submit provider prompts, change queue records, or restart the watcher.
