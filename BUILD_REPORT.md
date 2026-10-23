# SiteTask AI V2 Build Verification Report

## Build environment

- Date: 2026-07-17
- Platform: Windows 11 x64
- Python: 3.12.13
- PyInstaller: 6.21.0
- Build mode: `onedir`, windowed, no UPX
- Output: `dist/SiteTaskAI/SiteTaskAI.exe`

## Final build result

- Clean-build regression gate: 196 passed, 0 failed, 0 skipped
- PyInstaller exit code: 0
- Executable size: 10,368,325 bytes
- Distribution size: 150,674,733 bytes
- Distribution file count: 819
- Executable SHA-256: `DD5CA53D78F5DD68EB47D1B3DE1F491D2F6CF9506969A711A9C14DB62F98FD7C`

PyInstaller embedded the application icon and collected PySide6, SQLite,
dateparser, OpenAI SDK, keyring, winotify, logging code, and application
resources. Reported missing modules are conditional cross-platform or optional
integrations; none prevented the verified Windows workflows.

## Packaged application verification

The executable built from the logging-enabled source was started directly from
the distribution directory with `OPENAI_API_KEY` absent.

- The process remained responsive and exposed a `SiteTask AI` window.
- First run created `config/settings.json` and `data/sitetask.db`.
- First run created `logs/sitetask.log`.
- The log contained the `Application starting` event.
- No API Key was required and no paid API request was made.
- At the minimum `340 x 480` geometry, five tasks across Overdue, Today,
  Tomorrow, and Day After Tomorrow were visible without a scroll bar.
- Double-clicking a packaged task opened the Edit Task dialog.
- The bottom input panel was collapsed by default, expanded from `+ Add Task`,
  and no duplicate bottom View All Tasks button was present.

Earlier packaged acceptance also verified task creation, All Tasks, pin geometry,
close-to-tray, Settings without a key, dark resources, and application/tray icons.
The post-build UI fixes were checked in a live source window and included in this
final package.

## Clean distribution rebuild

After runtime verification, the complete build script was run again. It replaced
the distribution and removed the generated settings, database, and logs. The
final distribution contains none of the validation user's runtime data.

## Delivery archive

- Archive: `SiteTaskAI-windows-x64.zip`
- Archive size: 65,475,174 bytes
- Archive SHA-256: `DAE1D3C6AE59C5929294C178BEF6590089D8D42FD258F5138B4474465C5C234A`

The archive contains the complete `onedir` runtime. `SiteTaskAI.exe` must remain
beside `_internal`; copying only the executable is unsupported.

## Gate decision

The latest logging-enabled executable was built and run successfully. A second
clean build produced the final data-free distribution and delivery archive.
