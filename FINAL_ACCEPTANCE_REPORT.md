# SiteTask AI V2 Final Acceptance Report

## 1. Completed V1 functionality

- Frameless, draggable, resizable dark Windows desktop Widget
- Saved position, size, pin state, and persistent always-on-top toggle
- Close-to-tray, tray restore, tray actions, and explicit tray Exit
- Reversible current-user Windows startup
- SQLite task persistence for unrestricted due dates
- Widget visibility limited to overdue plus today, tomorrow, and day after tomorrow
- All Tasks filters, search, editing, deletion, completion, restore, and duplication
- Quick Task, full task editor, all-day tasks, completion delay, and Undo
- Compact 50px task cards, double-click editing, and a collapsible input panel
- One-hour-before and at-due-time Windows notifications with deduplication
- Resilient settings, rotating logs, redaction, and global exception handling

## 2. Completed V1.5 functionality

- Chinese and English relative date and time parsing
- Weekdays, next week, next month, explicit dates, future dates, and cross-year dates
- Runtime local date, time, and timezone resolution
- Title cleanup, category classification, priority suggestion, confidence, and ambiguity output
- Configurable default due time and all-day mode
- Mandatory editable preview before task creation

## 3. Completed V2 functionality

- Local-first parser routing with configurable threshold
- Optional OpenAI fallback for low-confidence input
- Pydantic structured AI response validation
- No invented dates; missing or ambiguous dates require confirmation
- Far-future AI dates remain valid and are never moved into the widget window
- Secure keyring/Credential Manager storage with environment-variable fallback
- AI enable switch, model setting, masked key state, and connection test
- Graceful no-key and AI/network failure behavior
- Mock-only AI automated tests with no paid API requests

## 4. Explicitly unimplemented functionality

No Gmail or Outlook reading, automatic email tasks, meeting recording or
transcription, cloud sync, collaboration, login, mobile/Web app, team roles,
automatic email sending, attachments, kanban, Gantt, project cost, background
server, online database, WorkerW embedding, multiple AI providers, or multi-task
extraction was implemented.

## 5. Stage Git commits

| Stage | Commit | Message |
| --- | --- | --- |
| 0 | `48a8df2` | `chore: initialize sitetask project` |
| 1 | `9079d51` | `feat(settings): add resilient application settings` |
| 2A | `d8f285a` | `feat(db): add task models and migrations` |
| 2A fix | `1b9375c` | `chore: stabilize local test environment` |
| 2B | `b6b3a1a` | `feat(db): add task repository CRUD` |
| 2C | `c79999c` | `feat(db): add task visibility queries` |
| 3 | `c152b0b` | `feat(ui): add minimal frameless widget shell` |
| 4 | `16068e3` | `feat(window): add persistent pin toggle` |
| 5A | `c89b2d0` | `feat(ui): display grouped widget tasks` |
| 5B | `a54f1cc` | `feat(ui): refresh task window and show empty states` |
| 5C | `8cdc4dd` | `feat(tasks): add task card interactions and undo` |
| 6A | `c51dae1` | `feat(tasks): add quick task creation` |
| 6 pre-fix | `8d39e22` | `fix(window): support frameless resize` |
| 6B | `8f96d66` | `feat(tasks): add full task editor` |
| 7A | `d11f347` | `feat(tasks): add all tasks filters` |
| 7B | `51d7471` | `feat(tasks): add all tasks search and actions` |
| 8 | `f626610` | `feat(tray): add system tray integration` |
| 9A | `c4b1f81` | `feat(parser): add local relative date parsing` |
| 9B | `9246926` | `feat(parser): add future date parsing` |
| 9C | `be5dded` | `feat(parser): add task semantics and confidence` |
| 9D | `f9d7494` | `feat(parser): add local task preview flow` |
| 10A | `73da4ee` | `feat(ai): add secure credential service` |
| Input fix | `de63bd5` | `fix(tasks): use date and time pickers for quick add` |
| 10B | `835ffa4` | `feat(ai): validate structured task responses` |
| 10C | `fec124f` | `feat(ai): route low-confidence tasks to AI` |
| 10D | `6d815a1` | `feat(ai): connect settings and preview workflow` |
| 11 | `bd58d23` | `feat(notifications): add due task reminders` |
| 12 | `1fde328` | `feat(startup): add reversible Windows auto-start` |
| 13 | `66a3a26` | `feat(ui): add global dark theme and high-DPI support` |
| 13 fix | `85cff1d` | `fix(ui): unify flat title bar controls` |
| 13 fix | `a8e02e4` | `fix(ui): stabilize narrow task layout` |
| 13 fix | `d2e709c` | `fix(ui): unify date picker styling` |
| 14 | `65a4b4b` | `test: record V2 regression gate` |
| 15A | `da93447` | `build: add Windows packaging scripts` |
| Branding | `87639fc` | `feat(branding): add SiteTask application icon` |
| 15B | `ac4c842` | `build: verify packaged Windows application` |
| Post-build fix | `ffca8c5` | `fix(ui): center task summary text` |
| Post-build fix | `16129f1` | `fix(ui): vertically center task summary` |
| 16A | `dde3542` | `feat(logging): add resilient rotating logs` |
| Post-acceptance UI | `c973956` | `feat(ui): add compact collapsible task view` |

The final documentation commit is recorded after this report is committed.

## 6. Actual test result

- Final suite: 196 passed, 0 failed, 0 skipped
- Python compilation: passed
- Tests include repository, visibility, UI, parser, mocked AI, credentials,
  notifications, startup, settings recovery, icon resources, logging, redaction,
  and global exception handling.
- No automated test called a paid API.

## 7. Actual packaging result

- PyInstaller 6.21.0 `onedir`, windowed, no UPX
- Output: `dist/SiteTaskAI/SiteTaskAI.exe`
- Executable SHA-256: `DD5CA53D78F5DD68EB47D1B3DE1F491D2F6CF9506969A711A9C14DB62F98FD7C`
- ZIP SHA-256: `DAE1D3C6AE59C5929294C178BEF6590089D8D42FD258F5138B4474465C5C234A`
- The latest executable was actually started without an API Key.
- First-run settings, database, and logging were observed.
- A second build produced a clean distribution with no validation data.

## 8. How to run

For the Windows package, extract the complete ZIP and double-click
`SiteTaskAI.exe`; keep `_internal` beside it. For source use, run
`scripts/setup.bat`, then `scripts/run.bat`.

## 9. API Key configuration

Open Settings, enable AI parsing, enter an API Key and model ID, test the
connection, and save. The key is stored under service `SiteTaskAI`, username
`openai_api_key`, in Windows Credential Manager/keyring. `OPENAI_API_KEY` is the
fallback. The key is not stored in JSON or normal logs.

## 10. Data, configuration, and log locations

Relative to the executable directory in a packaged build, or project root in
development:

- Database: `data/sitetask.db`
- Settings: `config/settings.json`
- Corrupt-setting backups: `config/settings.corrupt-*.json`
- Rotating log: `logs/sitetask.log`

## 11. Known limitations

- Windows 10/11 x64 only; the executable is not digitally signed.
- The full `_internal` directory is required.
- AI depends on network, credentials, model access, and possible API cost.
- Natural-language input extracts exactly one task.
- Timed notifications require the application to remain running; all-day tasks
  do not have a notification time.
- Long sleep beyond the notification grace period can miss an old reminder.
- Notification pause is session-only.
- Unusual or highly ambiguous local language still needs manual confirmation.

## 12. Upgrade recommendations

Before expanding integrations, prioritize signed releases, import/export and
backup UX, explicit Windows resume-event handling, configurable local parsing
dictionaries, and an updater strategy. Any V3 email, meeting, sync, or cloud
feature should require a separate privacy review, permission model, staged
implementation, and dedicated tests.

## Final decision

SiteTask AI V2 meets the scoped desktop task-management, local parsing, optional
AI parsing, storage, notification, security, testing, and Windows packaging
requirements. Features explicitly excluded from V2 remain unimplemented.
