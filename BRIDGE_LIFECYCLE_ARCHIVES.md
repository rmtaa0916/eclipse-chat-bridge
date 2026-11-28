# BRIDGE managed console and archive compression

The managed console preserves existing startup and monitoring behavior. A default session
attempts a queue-aware shutdown at exit; active work or uncertain ownership leaves the
service running. Explicit commands keep their previous behavior.

Archive compression uses one bounded, verified gzip snapshot per applied housekeeping
cycle and retains source JSON by default. Ten recent snapshots and snapshots younger
than 24 hours are excluded. Restore with:
  python3 bridge_archive_compression.py --restore backups/bridge_EXAMPLE.json.gz
Original replacement is deliberately not enabled until all archive consumers are audited.

The housekeeping integration patch targets the installed queue-based watcher architecture;
older Git baselines may require the queue and housekeeping dependencies first.
The actual service must reload the updated module before the hook becomes active.

## Experimental architecture

The queue-based watcher, housekeeping, supervisor and supporting modules are now present. The receipt recovery and archive compression hooks are integrated into their source files. The historical patch files are retained as development records, not as additional installation steps. Set ECLIPSE_DOC_ID and ECLIPSE_BRIDGE_RECOVERY_DOC_ID explicitly for the authorized primary document, and optionally ECLIPSE_GEMINI_DOC_ID for the secondary document. Archive compression retains original JSON by default. Unit tests do not establish live operation of a fresh installation.
