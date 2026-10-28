# Deployment and rollback

This source contains no provisioned account or credentials. Test in an isolated checkout
using LOCAL-TESTING.md first. SQLite on the desktop remains authoritative.

1. Install Python dependencies and run desktop tests; run `npm ci`, `npm test` and
   `npm run check` inside `worker`.
2. Create your own Cloudflare D1 database. Copy `wrangler.production.example.toml` to
   the ignored `wrangler.production.toml`; set the D1 ID and Worker name.
3. Apply `worker/schema.sql` to that database using Wrangler with the explicit production
   config. Generate offline credentials with `scripts/cloud_admin.py --db-id <UUID>
   --output <private-directory-outside-repository>`. The UUID identifies the desktop
   task database, and is different from the Cloudflare D1 resource ID.
4. Put the generated PEPPER into the bridge Worker's secret store using Wrangler
   `secret put PEPPER`; apply the generated provision.sql using the same explicit config.
   Keep all generated materials outside the repository. Deploy the bridge Worker.
5. In desktop Cloud bridge settings enter your bridge URL and bridge credential.
   Verify identity handshake, task snapshot and command receipts with synthetic tasks.
6. Set up the separate MCP service as described in DOT-MCP.md.

Before replacing an existing installation, exit the tray app and back up the entire
installation, database, settings and identity together. Do not overwrite an open database.
Build with `scripts/build.bat` and retain the complete onedir bundle. Run the packaged
`--self-test` before cutover. New schemas must not be opened with older executables.
To roll back, stop the new app and restore the matching old application and database
backup together. Restored identities may require the documented cloud recovery flow;
never disable fencing or manually reset sequence waterlines to force synchronization.

Do not upload private configuration, provision.sql, PEPPER, credentials, pairing code
files, task databases, backups, logs or generated OAuth state. Git ignore rules are a
convenience; inspect the staged diff before every publication.
