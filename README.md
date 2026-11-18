# StabilityConsole v0.3.0

Windows desktop application for application tracking, confirmed profile details, document review, job-search sessions and semi-active Gmail synchronization. Gmail checks run only while the app is open. Closing the app stops sync; no service, startup task or cloud worker is installed.

**Open `Launch-StabilityConsole.bat` at the repository root.** Pull the latest repository first. The source folder retains its historical `StabilityConsole-v0.1.0` name for compatibility; the code inside is now v0.3.0. The existing v0.1.0 ZIP is historical and does not contain this update.


## Track job search sessions

Open **Job-search workflow** and choose **Import session report** to bring a private report from the assisted job search into the app. Review its account and status summary first. The import preserves stable application IDs, CV versions, submission and bounce evidence, confirmed profile fields and document approvals. Reimporting the same report does not create duplicate applications. Local edits are preserved. Failed deliveries, blocked work and drafts remain distinct from sent applications. Double-click an evidence row to inspect its sources.

Choose **Start session** when beginning useful work and **Complete session** when finished. The app schedules a read-only Gmail check five minutes later, even when interval sync is disabled. It needs an already configured Gmail connection and an open app. A waiting check survives restart; an interrupted check becomes UNKNOWN rather than a stale success. Missing Gmail setup shows BLOCKED with a retry action. Historical checks imported from a report are labeled REPORTED. No application sending or background service has been added.

In **Confirmed profile**, review or edit facts without assuming unknown details. In **Documents and approval**, link a local file and approve its exact SHA-256 only after reviewing it. A changed document is a different revision and cannot inherit the old approval. Imported document states describe reported external approval/sending; they are not fresh verification of local bytes. Your documents, applications, personal facts and email evidence stay in the private local database, outside this public repository.

The ChatGPT scheduled search continues separately. This desktop integration tracks its reports; it does not embed or execute ChatGPT automations. See [session report format and recovery](docs/session-report.md).

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

- **INSPECTED:** the current Tk/SQLite application and existing read-only Gmail collector.
- **IMPLEMENTED:** private report import, stable application links and submission evidence, confirmed profile fields, document revision approval, five-minute session mail checks and recovery/cancellation. Existing Gmail setup, manual status review and public-advert lookup remain available.
- **TESTED:** 39 controlled tests through the launcher. Coverage includes real SQLite migration backups and rollback, repeated imports, preservation of local edits and missing fields, separate failed-delivery/withdrawal states, exact-hash approvals, delayed checks, restart recovery and partial/failed/cancelled collection. Network responses in these tests are controlled fixtures.
- **TESTED on Windows with Python 3.14 and Linux with Python 3.12:** the exact Windows batch launcher checks and real Tk GUI workflow; report import twice through the interface, profile/document rows, an unconfigured-mail blocker, shutdown and database reopening. [CI evidence](https://github.com/chenz9000/StabilityConsole/actions/runs/44327823789) and [verification record](verification-v0.3.0.json). These are actual runner executions, not syntax-only checks.
- **UNKNOWN on the user's target:** Windows 11 installation, Google OAuth/DPAPI and live Gmail/browser operation with the user's account. CI success is not proof those external prerequisites have been completed.

Offline tracking needs Python with Tcl/Tk. Integration setup needs Python 3.11+ and an installed Edge/Chrome browser. No private reports, credentials, mail data or local databases belong in this public repository. Source checksums use canonical UTF-8 text with LF line endings, as described in [the source manifest](source-manifest-v0.3.0.json).

## Management summary

Version 0.3.0 brings externally completed job-search work into the local register, keeps confirmed facts and document approvals with their evidence, and schedules a mailbox check five minutes after session completion. Failed attempts do not count as sent applications. Existing records are backed up and preserved. The Windows lock-contention error discovered during target checks is fixed. Controlled and GUI checks pass on Windows and Linux; live account setup remains an external verification step.
