# MCP / OAuth setup

The independent MCP Worker calls the bridge through a service binding. It exposes task
reads and asynchronous editing commands, not arbitrary execution on the desktop.
The desktop must be running and online to apply commands; check each command receipt.

1. Copy `worker/wrangler.mcp.example.toml` to ignored `worker/wrangler.mcp.toml`.
   Configure your MCP HTTPS origin, bridge HTTPS origin, desktop database UUID,
   D1 resource ID, dedicated OAuth KV namespace, rate-limit namespace and bridge service.
2. Apply `worker/mcp-schema.sql` to the same D1 database with this explicit config.
3. Provision an assistant credential for the same desktop database (prefer a dedicated
   MCP credential). Store it as the MCP Worker's `ASSISTANT_TOKEN` secret. Never embed
   it in TOML, source, ChatGPT instructions or the browser authorization form.
4. Deploy with the explicit MCP config. Configure your client with
   `https://your-mcp-worker.example.com/mcp` and OAuth authentication.
5. Run `python scripts/issue_dot_pairing.py --db-id <desktop-database-UUID> --output
   <private-file-outside-repository>`. This requires authenticated Wrangler with D1
   access. Enter the code only on your MCP authorization page. It expires after
   24 hours and is consumed once; issuing another invalidates unused codes for that DB.

OAuth supports PKCE S256, client metadata discovery, dynamic registration, resource
binding, refresh and revocation. Callback URLs are restricted to validated ChatGPT
HTTPS callback paths. The authorization form binds consent to the browser and keeps
same-origin protection; its CSP allows only the exact validated callback destination.

Tools cover connection status, list/mirror reads, command status/cancellation, live
desktop reads, create, update, complete, reopen, soft delete and restore. Writes require
tasks:write; use stable request IDs for retries and current revisions for edits.
No permanent deletion tool is exposed. A queued command is not a successful task edit.

Revoke OAuth refresh tokens through the revocation endpoint when disconnecting.
For emergency service shutdown revoke the dedicated MCP API credential; preserve
the separate desktop bridge credential. KV revocation propagation is not instantaneous.
