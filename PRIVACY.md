# Keeping private data out of public changes

The application stores tasks locally. Its database, local queue, logs and settings
are private runtime files, even when a filename looks like harmless JSON.

- Do not commit `data/`, `logs/`, local `config/` files, environment files,
  database copies, exports, backups, assistant state, screenshots or used builds.
  `config/settings.example.json` is the checked-in configuration example.
- Queue requests, receipts, archives and rejected requests can contain full task
  text, contact information and source-mail links. The CLI `read` output is also
  private. Do not paste these into public issues, CI logs or pull requests.
- Use invented examples and reserved example domains. Remove personal home
  paths, mailbox links and project identifiers from documentation and fixtures.
  Public author attribution and GitHub noreply commit addresses are intentional.
- API credentials belong in the OS credential manager or local environment.
  AI parsing sends the entered text to the configured provider when enabled;
  review confidentiality requirements before enabling it.
- Share only a fresh build made in a clean checkout. Never archive an installation
  that has been used with real tasks. Inspect the entire archive, including binary
  metadata and screenshots, before uploading it.

## Before pushing

Stage only the intended source changes, then run:

```powershell
python scripts/check_repository_privacy.py
python -m unittest discover -s tests -p test_repository_privacy.py
```

The guard examines staged Git blobs, including force-added ignored files. It
reports paths, line numbers and categories without echoing detected values.
To check a committed snapshot, use `--revision HEAD`. The privacy workflow runs
the same guard in CI. Ignore rules and CI do not prevent a secret from being
uploaded: run the local check before pushing.

This is a conservative heuristic check, not proof that a repository is free of
private material. Review diffs, new image assets, documents and dependencies
manually; contact details or business records may not match a pattern. Existing
legacy queue exclusions remain in code to preserve protection behavior.

## If something was already published

Removing it in a later commit does not remove earlier commits, pull request
diffs, cached views, forks or downloaded copies. Avoid repeating the value in
issues or commit messages. Assess exposure privately; credential revocation,
history rewriting, artifact deletion and cache removal require a separate,
explicitly approved recovery plan. Keep local runtime data out of that process.
