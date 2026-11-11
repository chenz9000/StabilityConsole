# StabilityConsole v0.2.0

Windows desktop application for application tracking, daily actions and semi-active Gmail synchronization. Gmail checks run only while the app is open. Closing the app stops sync; no service, startup task or cloud worker is installed.

**Open `Launch-StabilityConsole.bat` at the repository root.** Pull the latest repository first. The source folder retains its historical `StabilityConsole-v0.1.0` name for compatibility; the code inside is now v0.2.0. The existing v0.1.0 ZIP is historical and does not contain this update.

## First Gmail connection

1. Open **Gmail & advert evidence → Setup support**. The app creates/reuses a private local Python environment and installs the pinned dependencies. It downloads about 50–70 MB of Python libraries on Windows; it does not download or replace Edge/Chrome. Network or installation failures are shown. Close and reopen using the same root launcher after setup.
2. Create a Google Cloud project (or use one you control), enable the Gmail API and configure Google Auth for your account. For a personal Gmail address use an **External** audience, not Workspace-only Internal. If the app is in Testing, add your Gmail address as a test user. Create an **OAuth Desktop app** client, download its JSON, then use **Import OAuth client** in the app. Do not upload the client file, tokens or Gmail evidence to this public repository.
3. Choose **Connect Gmail** and complete Google's read-only consent in your normal browser. The app checks and displays the connected Gmail address. OAuth client configuration and tokens are encrypted with Windows DPAPI under `%LOCALAPPDATA%\StabilityConsole`, bound to your Windows user. No plaintext-token fallback is used. Testing-mode grants can expire and require reauthorization; the app does not claim perpetual authorization.
4. Enter application titles in the application register. Add employer/location when known. Enable **Sync while app is open** and save settings. Default interval: five minutes after the previous run finishes, adjustable from 1–120 minutes. Initial history: 180 days, adjustable. **Sync now** works independently of automatic scheduling.
5. **After sync: browser lookup** is enabled by default. Choose installed Edge (`msedge`) or Chrome (`chrome`). Searches open separate visible browser windows without attaching to your normal profile. Only the entered title, employer and location are sent as public search terms, not your message bodies or private application references.

Official setup reference: https://developers.google.com/workspace/gmail/api/quickstart/python

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
- **IMPLEMENTED:** Gmail OAuth/collection, app-lifetime scheduling, matching/review, visible-browser research, blank-field enrichment, encrypted authorization storage and first-run setup.
- **TESTED (controlled Linux execution):** original offline tests and Gmail processing/enrichment tests, including pagination, account isolation, deduplication/restart, linked replies, failed/cancelled collection, concurrent edits, no overwrites, ambiguous/expired adverts and worker/instance locks. Run the exact launcher path with `Launch-StabilityConsole.bat --self-test` on Windows; these are controlled fixtures, not live Gmail/browser proof.
- **TESTED:** dependency installation on Python 3.12 Linux and pinned wheel resolution/download for Windows x64 Python 3.14. Dependency availability is not Windows execution evidence.
- **UNKNOWN / target verification outstanding:** Windows 11 launcher execution, Windows DPAPI round-trip, interactive Gmail OAuth, live Gmail synchronization and installed Edge/Chrome end-to-end search/autofill. The current build environment has no usable Tk display; native desktop focus/input also prevented GUI verification. No claim of a fully working target workflow is made from the controlled tests.

Offline tracking requires Python with Tcl/Tk. Integration setup requires Python 3.11+ and an installed Edge/Chrome browser. Windows 11 x64 with Python 3.14 is the dependency-checked target; other architectures remain unverified. No user credentials, Gmail messages, databases or private logs belong in this public repository.

## Management summary

Version 0.2.0 adds Gmail collection while the app is open and a post-sync browser research/review path. It preserves existing records and protects ambiguous updates. Google OAuth setup and Windows end-to-end validation remain the final operational prerequisites; this release is implemented and controlled-tested, not target-verified.
