# Import a job search session

Open **Job-search workflow**, choose **Import session report**, select a private JSON report, and review the account and status summary before importing. Keep reports and database backups private. They may contain application evidence and personal information. Do not commit them to this public repository.

Imports record actions performed elsewhere. They do not send applications, connect Gmail, or turn a reported confirmation into a new live check. Application evidence is available by double-clicking its row. Imported Gmail thread IDs let the existing read-only collector find replies which omit the job title, within the report's email account.

Importing the identical report twice does nothing. A newer report with the same namespace and external application IDs adds evidence and updates only fields still equal to their previous imported values, or currently blank. Local edits are preserved. Missing fields never erase recorded CV versions or other details. An existing application with exactly the same title, employer and source URL is reused without overwriting its manually recorded state.

Use **Cancel file operation** to stop an import or file-hash operation. File reads and an existing SQLite lock wait must return before cancellation is observed. An incomplete import rolls back as one transaction; an import already committed is retained. Closing the app also requests cancellation.

## Report format

Use UTF-8 JSON, at most 5 MiB, with `schema_version: 1`. The example below is fictional demonstration data. A sent application requires submission evidence. Drafts, blocked applications and failed deliveries remain distinct states and are not included in the progressed-application metric.

```json
{
  "schema_version": 1,
  "namespace": "career-search",
  "report_id": "example-session-2026-01-01",
  "account": "candidate@example.org",
  "session": {
    "title": "Example job-search session",
    "started_at": "2026-01-01T08:00:00+00:00",
    "completed_at": "2026-01-01T08:15:00+00:00",
    "check_detail": "External source reports a completed mail check."
  },
  "applications": [
    {
      "external_id": "EXAMPLE-001",
      "title": "Support Technician",
      "employer": "Example Employer",
      "area": "Example town",
      "status": "SENT",
      "url": "https://example.org/jobs/1",
      "cv_version": "Support-CV.pdf",
      "applied_on": "2026-01-01",
      "notes": "Externally submitted; employer review is unknown.",
      "evidence": [
        {
          "kind": "submission",
          "message_id": "example-message-id",
          "thread_id": "example-thread-id",
          "url": "https://mail.google.com/mail/#all/example-message-id",
          "recipient": "recruitment@example.org",
          "detail": "Source report checked the sent message and CV attachment."
        }
      ]
    }
  ],
  "profile": [
    {
      "name": "Availability",
      "value": "",
      "state": "UNKNOWN",
      "source": "Candidate has not supplied this detail."
    }
  ],
  "documents": []
}
```

Application states: `SENT`, `EMPLOYER-ACKNOWLEDGED`, `REPLIED`, `INTERVIEW`, `REJECTED`, `WITHDRAWN`, `DRAFT`, `BLOCKED`, `FAILED`, `EXPIRED`, `UNKNOWN`, `DISCOVERED`.

Profile fields use `CONFIRMED`, `REVIEW REQUIRED` or `UNKNOWN`, with a source. A local edit is retained on later imports. There are no assumed salary, licence, transport, availability, authorization or role-level defaults.

Document entries require `document_key`, `filename`, the exact 64-character `sha256`, and a `state` (`DRAFT`, `REVIEW REQUIRED`, `APPROVED`, `SENT`, `BLOCKED`, `FAILED`, `UNKNOWN`). Optional `application_external_id` connects the revision to a record in the same report; `source` explains the review/send evidence. `APPROVED` describes approval of those exact bytes. Imported states are historical reports, not proof the local file exists. Choose **Link local file revision** to associate actual bytes, review them, then **Approve reviewed file**. A modified file cannot reuse approval for its old hash. Approval never sends a document.

## Session mail check

Choose **Start session** and do useful job-search work. **Complete session** records completion and schedules the existing Gmail collector five minutes later. It uses the already configured read-only account; it never starts a new consent flow or sends mail. Advert enrichment is disabled for this final check so that it stays a mailbox check.

The app must be open. A waiting deadline survives restart and runs when overdue and Gmail is available. Missing setup shows `BLOCKED`; complete setup and use **Retry due mail check**. Running checks interrupted by shutdown become `UNKNOWN`, never `PASS`. Collection errors, cancellation and partial pagination retain their real outcomes, with the associated Gmail run ID when available. Imported session history is labeled `RECORDED` / `REPORTED` and does not launch a fresh check.

The desktop does not run the ChatGPT scheduled task or an autonomous application agent. That task continues separately. Use a current report to bring its work into the local register.
