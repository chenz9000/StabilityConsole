# Stability Console v0.1.0

A private, offline Windows desktop tool for maintaining job-application records and daily actions. No promises of automatic job discovery or sending.

## First-run workflow
1. Install Python 3.10+ including Tcl/Tk (`tkinter`). No third-party Python packages are required.
2. Extract all files to one writable folder. Double-click `Launch-StabilityConsole.bat`.
3. Create an application with actual employer, source URL and status. Do not mark `Applied` unless you have submitted it.
4. Assign follow-up dates; the Overview displays due or overdue actions.
5. Open **Browser job search**, enter multiple areas separated by commas, prepare searches and double-click to open a real search in your browser. This does **not** import or verify any listings.
6. Use CSV export and database backup. Your data is stored in `%LOCALAPPDATA%\StabilityConsole\stability.db` unless overridden using `STABILITY_CONSOLE_DATA`.

## Accuracy / limitations
- No automatic job collection, CV generation, sending, inbox monitoring, notifications outside the app, or background services.
- `Applied` and all other statuses are user-entered, not verified by employer communications.
- No network activity is performed by the application except opening a user-selected external URL in the system browser.
- Database remains on the local machine. No telemetry. No saved credentials.
- Python console exceptions are logged to `stability.log` in the data directory. Validate Python and Tkinter installation on the target Windows device.
- Required Microsoft Windows end-to-end validation is pending. Linux virtual-display tests are not Windows validation.
- Backups can be taken through the Overview button using SQLite's online backup API.

## Acceptance criteria
- Save a job with source, location, CV version, notes, status and due date; restart; verify same entry.
- Change its status and verify a recorded event.
- Create and complete a daily action; reopen and verify persistence.
- A due follow-up appears on the Overview.
- Browser search links reflect each entered area and keyword without presenting any jobs as found.
- Export a CSV and create an SQLite backup.

## Version summary
**Changes:** new independent offline application; no reuse or modification of existing GitHub repositories, no import of historical job data.
**Verification:** see `verification.json` bundled in release.
**Limitations:** live job discovery and Windows-specific execution not verified. No automation or sending.
**Management overview:** usable local workflow for keeping obligations and job applications from disappearing into scattered emails, with browser-assisted discovery clearly separated from evidence of actual vacancies.
