# Durable receipt recovery

The production queue-based watcher may be newer than repository HEAD. This commit records the independent recovery module, regression tests, and the reviewed hook patch. Do not apply the hook to a legacy watcher without its queue dependencies. The patch adds one rate-limited recovery attempt during idle polling, skips no-sync mode, uses a document allowlist and 24 KiB journal cap, and verifies readback before marking a terminal row synchronized. No latest-slot replacement or original task re-execution occurs. The live e145 receipt was recovered successfully. Restart is required to load the installed watcher hook.

Public deployment: set ECLIPSE_BRIDGE_RECOVERY_DOC_ID in the watcher service environment to the explicitly authorized document identifier. With no value configured, recovery is disabled.
