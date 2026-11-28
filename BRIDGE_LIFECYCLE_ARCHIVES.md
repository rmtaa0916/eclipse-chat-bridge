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

## Experimental branch compatibility

The legacy experimental watcher does not yet contain the queue, automatic housekeeping, or unified supervisor architecture required by the integration patches. The modules, managed launcher, and tests are included for development; the patches are not applied and do not enable automatic recovery or compression on this legacy branch. Integrate the newer queue-based architecture and validate the hooks before deployment.
