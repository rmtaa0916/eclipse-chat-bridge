# Gemini BRIDGE operating instructions
This managed header takes precedence over historical operational instructions below it. Preserve the existing Gemini V1 protocol examples and records; they are not commands to repeat.
- Use only the authorized configured Gemini document and the current user task. Do not send ChatGPT protocol requests through the Gemini document.
- Append one complete request with a new unique ID using the existing Gemini request markers and supported action schema. Do not modify accepted requests or resubmit because delivery is delayed.
- The unified watcher may accept both providers when explicitly configured. Verify that the secondary document and service are actually enabled; never start a duplicate watcher.
- Match the response ID in the Gemini diagnostic section. Distinguish queued, running, completed, failed and interrupted work. If output is bounded or marked partial, do not assume it is the entire result; use the authorized result retrieval path.
- Preserve protocol markers, receipts and queued requests. Housekeeping requires revision protection and local acknowledgment/backup safeguards. Do not manually delete active data.
- Respect user authorization, restricted paths and execution boundaries. Never request credentials, unrelated private data, unapproved destructive operations or authentication changes.
- Check the installed checkout and live status before claiming newer capabilities. Report actual blockers, and do not blindly replay interrupted work.
