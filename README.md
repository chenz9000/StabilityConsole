# StabilityConsole v0.2.1

Windows desktop application for application tracking, daily actions and semi-active Gmail synchronization. Gmail checks run only while the app is open. Closing the app stops sync; no service, startup task or cloud worker is installed.

**Open `Launch-StabilityConsole.bat` at the repository root.** Pull the latest repository first. The source folder retains its historical `StabilityConsole-v0.1.0` name for compatibility; the code inside is now v0.2.1. The existing v0.1.0 ZIP is historical and does not contain this update.

## Set up Gmail inside the app

1. Pull the latest repository and open the root **Launch-StabilityConsole.bat**.
2. In **Gmail & advert evidence**, choose **Set up Gmail**.
3. Follow the wizard. It checks what is missing, installs pinned support libraries after you choose Install, reopens the app automatically and resumes your place. Existing support is reused. No terminal commands, manual Python-package installation or manual restart are required.
4. Finish Google's guided browser steps if needed, choose the downloaded Google connection file in the wizard, then sign in and choose **Start syncing**.

The wizard shows one Google step at a time and opens the official page for that step. It includes the personal-Gmail External audience/test-user settings, read-only access value, Desktop client download and file validation. An existing protected connection file skips these registration steps. Existing stored authorization is checked against Gmail rather than treated as proof that it still works.

**Remaining external prerequisite:** this source does not include a shared registered Google sign-in client. Until one is supplied, a Google project and Desktop client must be registered once, by you on Google's pages. The app guides that process; it does not silently create a cloud project, accept Google's terms, bypass sign-in or claim registration succeeded from a checkbox. A valid connection file plus a successful Gmail profile check are required before the wizard offers Start syncing. This is a guided setup, not a claim that first-time setup is already a single Google sign-in click.

Setup progress is stored locally without credentials and resumes after the app-controlled restart. If automatic reopening fails, the normal root launcher resumes the saved wizard. Set up later closes the wizard; completed configuration and your existing records remain in place. Automatic mail checks pause while the wizard is open. The wizard body scrolls so longer steps and errors remain accessible.

Support installation downloads about 50–70 MB of pinned Python libraries on Windows and reuses installed Edge/Chrome. It does not download or replace your browser. OAuth configuration/tokens stay protected with Windows DPAPI under your Windows user; they are never sent to this public repository. Google test-mode authorization may expire and require signing in again.

Default mail interval: five minutes after the prior run finishes, adjustable from 1–120 minutes. Initial history is 180 days, adjustable. Browser enrichment is enabled by default and only fills corroborated blanks. All of these settings remain in the Gmail tab.

Official references used for the built-in guide:
- https://developers.google.com/workspace/gmail/api/quickstart/python
- https://developers.google.com/workspace/guides/configure-oauth-consent

## Email matching and web enrichment

- Read-only Gmail API; no send, delete, archive, label or attachment-download operations.
- Searches each entered application title. Employer evidence strengthens the match; a title-only match remains tentative. Review a message and **Link this thread** so later replies can match even when they omit the role title.
- Gmail message IDs are deduplicated per account. Pages are checkpointed, including a stable time window. Up to ten 50-message pages per application are processed per run; unfinished pages remain **PARTIAL** and continue next cycle. Previously linked threads retrieve only newly seen message bodies.
- After collection, up to three pending applications per cycle are researched through your selected browser. Google search uses title plus known employer/location; explicit public advert links in the relevant mail are also candidates. At most five advert pages are inspected per lookup.
- Individual schema.org `JobPosting` data supplies employer, exact advertised location, source URL, salary, employment type, dates and requirements where present. Automatic filling affects **only blank employer, location and advert URL fields**, and requires exact title plus corroborating employer/email evidence, no conflicts and one consistent advert among inspected candidates. Other advertised details remain attached to the review evidence. CV version, application status, sent date and follow-up dates are never guessed from the web.
- Existing fields are preserved, including edits made while lookup runs. Multiple different matching adverts, failed source checks, expired adverts, unconfirmed employers and title-only ambiguity require review. Source URLs, check times, match reasons, fields filled and review states are retained locally.
- No CAPTCHA bypass, account login, application submission, cookie-consent acceptance or profile-security changes. Browser policies, search-layout changes and site blocks can prevent lookup. Failures are visible, never replaced with invented details. Use **Lookup selected advert** to retry deliberately or **Open public web search** to inspect manually.
- Suggested email statuses remain review-only. Reading an acknowledgement does not silently change an application. **Accept suggested status** requires your click and confirmation.

## Preservation and recovery

The first Gmail schema addition makes `before-gmail-v0.2.0.db` before adding tables. Original application/task data remains in place. A single-instance lock prevents competing app instances for one data directory. One worker serializes Gmail, setup and browser operations. Cancelling a sync retains completed pages and pauses automatic scheduling until settings are saved again. Closing the app stops the worker and terminates its owned browser subprocess tree.

Disconnect removes local stored token access and disables auto sync; historical message evidence and tracking remain. Revoke Google consent separately in your Google Account if desired. Backups contain local email evidence as well as tracking; keep them private. On a different Windows account or after DPAPI recovery failure, reconnect rather than copying/decrypting tokens.

## Validation and evidence status

- **INSPECTED:** existing repository source and SQLite workflow; no Gmail integration existed before this update.
- **IMPLEMENTED:** Gmail OAuth/collection, app-lifetime scheduling, matching/review, visible-browser research, blank-field enrichment, encrypted authorization storage, resumable setup wizard and app-controlled restart.
- **TESTED (controlled Linux execution):** original offline tests and Gmail processing/enrichment/setup tests, including wizard prerequisites, no false Google-success transitions, resume checkpoints, restart lock hand-off, pagination, account isolation, deduplication/restart, linked replies, failed/cancelled collection, concurrent edits, no overwrites, ambiguous/expired adverts and worker/instance locks. Run the exact launcher path with `Launch-StabilityConsole.bat --self-test` on Windows; these are controlled fixtures, not live Gmail/browser proof.
- **TESTED:** dependency installation on Python 3.12 Linux and pinned wheel resolution/download for Windows x64 Python 3.14. Dependency availability is not Windows execution evidence.
- **UNKNOWN / target verification outstanding:** Windows 11 launcher execution, Windows DPAPI round-trip, interactive Gmail OAuth, live Gmail synchronization and installed Edge/Chrome end-to-end search/autofill. The current build environment has no usable Tk display; native desktop focus/input also prevented GUI verification. No claim of a fully working target workflow is made from the controlled tests.

Offline tracking requires Python with Tcl/Tk. Integration setup requires Python 3.11+ and an installed Edge/Chrome browser. Windows 11 x64 with Python 3.14 is the dependency-checked target; other architectures remain unverified. No user credentials, Gmail messages, databases or private logs belong in this public repository.

## Management summary

Version 0.2.1 adds one in-app Gmail setup wizard with automatic support installation, restart and recovery. It guides the remaining one-time Google registration and performs a real connection check before starting sync. Existing tracking and review behavior are preserved. Controlled tests pass; Windows GUI/restart, DPAPI and live Gmail/browser execution remain unverified.
