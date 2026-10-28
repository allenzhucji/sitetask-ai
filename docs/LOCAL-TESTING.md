# Local testing

Use a separate source checkout/copy. Tests create a database under that source
tree; never run them in the production installation or the original development
directory. Python 3.12+, Windows, Node 24 and npm are used in the verified setup.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python -m pytest -q
npm ci --prefix worker
npm test --prefix worker
npm run check --prefix worker
```

The shared `tests/vectors/cloud_v1.json` file has exact UTF-8 hex input and
canonical/hash expectations. Neither suite regenerates it during normal testing.

Real local D1/Durable Object/Qt test, using a fresh sibling private directory:

```powershell
.venv\Scripts\python scripts\cloud_smoke.py init ..\cloud-smoke
Set-Location worker
node scripts/local-seed.mjs ../../cloud-smoke
npx wrangler d1 execute DB --local --file=schema.sql
npx wrangler d1 execute DB --local --file=../../cloud-smoke/seed.sql
npx wrangler dev --local --ip 127.0.0.1 --port 8787
# In another terminal at the source root:
.venv\Scripts\python scripts\cloud_smoke.py run ..\cloud-smoke
```

This creates ephemeral local-only test credentials outside the source tree,
except ignored `worker/.dev.vars`, which supplies the local test pepper.
Never include these test files in a release archive. Stop Wrangler when finished.
Do not add `--remote` to any local command above.

Upgrade rehearsal uses SQLite's read-only backup API and verifies all original
task columns, integrity, rejection by old v4/v5 code and full snapshots after
removing the prunable event log:

```powershell
.venv\Scripts\python scripts\rehearse_upgrade.py --database C:\path\to\archived-copy.db --workdir ..\fresh-rehearsal
```

For deployment and executable packaging, see DEPLOYMENT.md. The OpenAPI file's server URL is deliberately a non-working placeholder.

Validation of the public source: 372 Python tests, 20 Worker tests and TypeScript
type checking passed. The development Python environment also emitted a Windows
Qt/OpenSSL loader diagnostic while running network tests; pytest still exited 0.
This is not a substitute for the packaged Windows TLS/self-test check.
