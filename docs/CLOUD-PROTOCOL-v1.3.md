# Site Task AI cloud protocol v1.3

Protocol version 1.3 supersedes versions 1.1 and 1.2. SQLite remains authoritative. The Worker is an authenticated
command mailbox and non-authoritative mirror. No cloud route or operation can
permanently delete a local task. Existing inbox acceptance rules remain unchanged.

## Review corrections

* H1: expired content is refused at every content ingress. Authorized `get`,
  `reopen` and `restore` with no submitted text remain legal. Only a current,
  authoritative active row can republish content. Permanent tombstones cannot
  be restored. Reference resolution includes completed and soft-deleted rows.
* H2: `as_of` comes from the durable SQLite AUTOINCREMENT waterline, in the same
  read transaction as all rows. `task_versions` retains each identity's latest
  sequence independently of the prunable change log. Migration 6 assigns initial
  versions to old tombstones and previously pruned identities.
* H3: installations that have enabled cloud access persist a guard in Windows
  Credential Manager. At startup they fence task creation before network work.
  A current identity handshake must pass before additions are allowed. SQLite's
  insert trigger enforces the fence for all writers. Restored/copied databases
  cannot automatically resume. Explicit reconciliation uses a durable request
  UUID, idempotent Worker epoch transition, paged content-free recovery metadata,
  one local transaction, then an atomic external checkpoint and full generation.
  Any interruption leaves the fence in place. Known inactive/expired state is
  preserved. A reused identity (different original creation time) or local row
  conflicting with a permanent cloud tombstone remains fenced. The local settings
  dialog can preview every conflict and, only after explicit confirmation, preserve
  each task under a fresh ID, clear managed references and tombstone its old local
  identity in one transaction. No automatic destructive repair is attempted.
* H4: historical command/receipt records carry a monotonically shortening
  deadline. All local episode deadlines survive reopening and are included in
  synchronization. Neither a reopen, late receipt nor a retry extends or restores
  old content. Reads enforce logical expiry; hourly cleanup removes stored content,
  including expired generation items. Local ledger receipts are content-free;
  the temporary receipt outbox is redacted on retry and deleted on acknowledgement.
* M1: move/reorder reserve a write transaction before reading, guard all task
  updates by pending/non-deleted state, check row counts, and roll back the whole
  operation on failure. Returned rows are read before commit.
* L1: the historical Windows baseline was **332 passed**, not 317. That figure
  describes the handed-off m5 baseline and must not be used as a claim about the
  later bridge build. The release verification report records current results.

## Implemented wire contract

Request keys are exactly `v, command_id, op, target, base_revision, fields, reason`.
Version is 1; UUIDs are lowercase canonical strings. Supported operations:
`create`, `update`, `complete`, `reopen`, `soft_delete`, `restore`, `get`.
`list` reads the mirror directly. Create assigns `CLOUD:<command_id>`; updates
require the current business revision. Complete/reopen protect deleted/cancelled
tasks. All operations enforce the suppressed-reference list locally.

Canonical JSON sorts ASCII object keys, emits compact UTF-8, rejects duplicate
keys, floats, unsafe integers and isolated surrogates. Text limits count Unicode
code points. Description allows newline/tab; titles disallow controls. The
checked-in byte vectors are shared by Python and TypeScript tests.

Immutable envelopes add database ID, authenticated actor, request hash, assigned
reference, accepted time and `execute_before = accepted_at + 7 days`. Epoch and
lease metadata are outside the immutable envelope. Limits: 32 KiB per envelope,
4 commands/128 KiB per lease batch, 192 KiB desktop pending, 256 KiB HTTP body.
Lease duration is at most 120 seconds; renewal never exceeds execute_before.
Old historical leases can prove a commit made before expiry. A receipt's result
hash covers only command_id/status/result_code/task_id/business_revision/change_seq.

Cloud execution, local ledger insertion and outbox insertion share one SQLite
write transaction. Replay checks channel, actor and request hash. UI/cloud writes
never advance the inbox automation's last_revision baseline. A failed/conflicting
command stops execution of the remainder of that delivered batch.

## Synchronization and recovery

Full generation is start → bounded items → finalize. The manifest hashes sorted
`[task_id, change_seq, business_revision, lifecycle]` tuples. Nothing becomes
visible before complete validation and atomic commit. Missing older rows become
content-free permanent tombstones; newer increments are preserved. Mirror rows
remain as waterlines. Same-version active confirmations are safe.

The desktop v1 implementation sends a full generation after a local sequence
change and at least daily. This deliberately favors an auditable small-database
implementation over incremental optimization. The Worker also implements the
ordered changes endpoint. Full generation currently caps at 10,000 identities.
The Worker loads the selected database's mailbox/mirror into its coordinator;
this is a single-user implementation, not a high-volume multi-tenant service.

Every database's command writes, leasing, receipts, generations, reconciliation
and cleanup pass through one Durable Object's serialized request queue. D1 batch
commits the state transition atomically. No external D1 write path is used during
normal operation. Tables contain JSON rows for mailbox, mirror and generation
state; authenticated token metadata is stored separately and contains only HMACs.

Reconciliation quarantines unfinished commands and marks acknowledged writes
beyond the restored watermark lost_by_restore. Old-history receipts cannot enter
the new epoch. Recovery preserves known lifecycle deadlines and identity counters;
it is not a content merge. Ambiguous forks require the reviewed local mapping flow.

## Credentials and local integration

Bridge credentials use `SiteTaskAI / cloud_bridge_token` in Windows Credential
Manager. An independent per-installation guard persists cloud enrollment across
restored config files. There is no credential file/environment fallback in the
desktop app. Only explicit test mode allows loopback HTTP. Production origins
must be HTTPS origins without userinfo, path, query or fragment. Redirects are
refused. Network requests have a 20-second total deadline and are cancellable.

Qt network objects live in a dedicated QThread; JSON copies return via queued
signals. SQLite stays on the main thread. The one-second shared execution gate
runs inbox then cloud within a four-command budget and pauses during interaction.
It retains the installation consumer lock while either channel is enabled.
Closing to tray does not stop the bridge. Explicit exit aborts network work and
waits for the thread; a running QThread is never force-terminated.

Assistant and bridge tokens have separate routes. No purge scope exists. v1
issues no mail-automation cloud token: mail continues via inbox. Defense-in-depth
mail cloud policy allows only existing PROJECT reference get/update; create is
deliberately refused until a separately specified mail enrollment contract exists.
No token, Authorization header or task body is logged by the bridge.

## Unchanged authorization limits

No public deployment, GitHub push, firewall modification, production replacement
or installation upgrade is authorized by this implementation. Release and rollout
require Example User's separate approval. Stop all old executables before any approved
upgrade and replace the matching CLI at the same time. Keep a matching executable,
runtime, database, integration directory and config backup for rollback.
