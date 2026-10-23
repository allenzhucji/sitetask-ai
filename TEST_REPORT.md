# SiteTask AI V2 Test Report

## Final regression gate

- Date: 2026-07-17
- Platform: Windows 11 x64
- Python: 3.12.13
- SQLite: 3.50.4
- PySide6: 6.11.1
- Pydantic: 2.13.4
- dateparser: 1.4.1
- OpenAI SDK: 2.46.0
- pytest: 9.1.1

## Results

| Test group | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Database, repository, and visibility | 13 | 0 | 0 |
| Windows UI and widget behavior | 66 | 0 | 0 |
| Local and mocked AI parsing | 86 | 0 | 0 |
| Settings and Windows services | 25 | 0 | 0 |
| Application branding | 2 | 0 | 0 |
| Logging, redaction, and exception handling | 4 | 0 | 0 |
| **Full suite** | **196** | **0** | **0** |

The groups are non-overlapping and contain the same 196 tests as the full run.
Qt unit tests use the offscreen platform. Native window, tray, pin, packaged
startup, first-run storage, and logging behavior were also checked on Windows.

## Acceptance coverage

- Far-future tasks persist without being forced into the three-day window.
- Tasks enter and leave the widget as the injected date or edited due date changes.
- Pending overdue tasks remain visible until completed, cancelled, or deleted.
- CRUD, completion, restore, duplication, search, filters, and undo are covered.
- Window resize, geometry, pin state, title controls, tray, and refresh are covered.
- At `340 x 480`, five tasks across four date groups fit without scrolling.
- Double-click editing and the collapsible Quick Task/AI Task panel are covered.
- Quick Task supports timed and all-day tasks with safe date/time validation.
- Chinese and English parsing covers relative, weekday, future, and cross-year dates.
- Parser routing prefers local output and uses only mocked AI in automated tests.
- Missing credentials are recoverable and do not disable offline features.
- Notifications are independent from widget visibility and deduplicated in SQLite.
- Settings corruption recovery and reversible user-level startup are covered.
- Rotating logging, API Key redaction, global exception handling, and logging failure fallback are covered.

## Native verification

The source application and packaged executable were started with
`OPENAI_API_KEY` absent.

- A responsive `SiteTask AI` window opened.
- Settings and SQLite were created on first run.
- `logs/sitetask.log` was created and recorded application startup.
- AI remained optional and no paid API call was made.
- Verification processes were stopped afterward.

## Commands executed

```powershell
python -m pytest tests/test_logging_service.py -q
python -m pytest -q
python -m compileall -q app tests
cmd /c scripts\build.bat
```

The compact-view release gate passed 196 tests before packaging and passed the
same 196 tests again during the final clean rebuild.

## Gate decision

The final regression gate passed with no failures or skips.
