# StabilityConsole

Job application tracking and management.

## Project baseline

Windows desktop application for offline application tracking, daily actions, follow-ups, and browser job-search shortcuts.

**Existing artifact:** Stability Console v0.1.0 was built and container-tested, but not yet tested on the user's Windows 11 system. The user uploaded the v0.1.0 ZIP and extracted source to this repository in commit `196e7967cdffed76c9a228f7b100ff74ab91f368`. Repository source is present and **INSPECTED at commit manifest level**, but a fresh checkout/build and Windows 11 validation remain outstanding.

Original v0.1.0 ZIP SHA-256:
`1bba47a7842715079d2b7ff6651917f5afce63429a37239716acd86ccfb275c7`

## Intended workflow

1. Launch one Windows desktop application.
2. Record an opportunity, its source URL, location, application status, CV version and follow-up date.
3. Track actions and deadlines without losing them on restart.
4. Generate browser job-search links for multiple areas, manually inspect results, and add real vacancies.
5. Export application history and back up the local SQLite database.

## Verification and limitations

- Source package: **uploaded to GitHub by the user**; verified from commit file manifest. Full source audit and target execution pending.
- SQLite, core logic and GUI: previously tested in Linux/container with controlled data.
- Windows 11 end-to-end execution: **UNKNOWN**.
- Automatic job discovery: **NOT IMPLEMENTED** in v0.1.0.
- Gmail synchronization and sending: **NOT IMPLEMENTED** in v0.1.0.
- No real vacancy or email may be marked verified without source evidence.

## Next two steps

1. Inspect uploaded v0.1.0 source against its original package, check for accidentally committed sensitive/runtime artifacts, then verify checkout and launcher on Windows.
2. Implement read-only Gmail OAuth synchronization with explicit account consent, reviewable message-to-application matching, deduplication, and visible failure states. Sending remains a separate approval-gated feature.

## Data and security

This repository is **public**. Never commit CVs, contact information, personal SQLite databases, Gmail messages, OAuth client secrets, access/refresh tokens, private logs or downloaded attachments.

User data belongs outside the repository, under `%LOCALAPPDATA%\StabilityConsole`. Do not infer application statuses from guesses or stale cached records.

## Release standard

Each version must report: changes, tests actually executed, target-machine verification, limitations and a short management summary. A successful build is not proof of a working end-to-end workflow.
