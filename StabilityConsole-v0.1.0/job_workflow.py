"""Local job-search reports, confirmed facts, document revisions and delayed checks.

Imported evidence is a report of an external action, never a new submission or
live Gmail verification. This module has no network or sending capability.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import backup, log, validate_date, validate_url
from mail_sync import init_mail

STATES = {
    'SENT': 'Sent', 'EMPLOYER-ACKNOWLEDGED': 'Acknowledged', 'REPLIED': 'Replied',
    'INTERVIEW': 'Interview scheduled', 'REJECTED': 'Rejected', 'WITHDRAWN': 'Withdrawn',
    'DRAFT': 'Draft', 'BLOCKED': 'Blocked', 'FAILED': 'Failed', 'EXPIRED': 'Expired',
    'UNKNOWN': 'Unknown', 'DISCOVERED': 'Discovered',
}
FACT_STATES = ('CONFIRMED', 'REVIEW REQUIRED', 'UNKNOWN')
DOC_STATES = ('DRAFT', 'REVIEW REQUIRED', 'APPROVED', 'SENT', 'BLOCKED', 'FAILED', 'UNKNOWN')
MAX_REPORT_BYTES = 5 * 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    return (value or utcnow()).astimezone(timezone.utc).isoformat(timespec='seconds')


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def ensure_schema(conn, root=None):
    """Add tables with a pre-migration backup; never rebuild existing tables."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_reports'").fetchone() and root:
        path = Path(root) / 'before-workflow-v0.3.0.db'
        if path.exists():
            path = path.with_name('before-workflow-' + uuid.uuid4().hex + '.db')
        backup(conn, path)
    init_mail(conn)
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS workflow_reports (
        report_id TEXT NOT NULL, digest TEXT NOT NULL, imported_at TEXT NOT NULL,
        source_file TEXT NOT NULL, summary TEXT NOT NULL, PRIMARY KEY(report_id,digest));
      CREATE TABLE IF NOT EXISTS workflow_links (
        source_id TEXT PRIMARY KEY, application_id INTEGER NOT NULL, baseline_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS workflow_evidence (
        source_id TEXT NOT NULL, evidence_id TEXT NOT NULL, application_id INTEGER NOT NULL,
        payload_json TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(source_id,evidence_id));
      CREATE TABLE IF NOT EXISTS workflow_facts (
        name TEXT PRIMARY KEY, value TEXT NOT NULL, state TEXT NOT NULL,
        source TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS workflow_documents (
        document_key TEXT NOT NULL, sha256 TEXT NOT NULL, filename TEXT NOT NULL,
        state TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL DEFAULT '',
        local_path TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        PRIMARY KEY(document_key,sha256));
      CREATE TABLE IF NOT EXISTS workflow_sessions (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
        check_due TEXT NOT NULL DEFAULT '', check_state TEXT NOT NULL DEFAULT 'NOT SCHEDULED',
        check_detail TEXT NOT NULL DEFAULT '', mail_run_id TEXT NOT NULL DEFAULT '');
    ''')
    conn.commit()


def recover_sessions(conn):
    """Interrupted execution is unknown; a waiting deadline survives restart."""
    with conn:
        conn.execute("UPDATE workflow_sessions SET state='INTERRUPTED' WHERE state='ACTIVE'")
        conn.execute("UPDATE workflow_sessions SET check_state='UNKNOWN',check_detail=? WHERE check_state='RUNNING'",
                     ('App closed before a result was recorded. Retry this check; no success is claimed.',))


def _text(value, name, limit=20000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(name + ' must be text within the supported size limit.')
    return value.strip()


def _items(report, key, maximum):
    items = report.get(key, [])
    if not isinstance(items, list) or len(items) > maximum or any(not isinstance(x, dict) for x in items):
        raise ValueError('Invalid ' + key + ' list.')
    return items


def validate_report(report):
    if not isinstance(report, dict) or report.get('schema_version') != 1:
        raise ValueError('Choose an Income Command workflow report with schema_version 1.')
    for name in ('report_id', 'namespace', 'account'):
        value = _text(report.get(name), name, 250)
        if not value:
            raise ValueError(name + ' is required.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', report['account']):
        raise ValueError('Report account must be an email address.')
    seen = set()
    for app in _items(report, 'applications', 1000):
        for key in ('external_id', 'title', 'employer', 'status'):
            if not _text(app.get(key), key, 1000):
                raise ValueError('Application ' + key + ' is required.')
        if app['external_id'] in seen:
            raise ValueError('Duplicate external application ID within this report.')
        seen.add(app['external_id'])
        if app['status'] not in STATES:
            raise ValueError('Unsupported application status: ' + app['status'])
        for key in ('area', 'url', 'cv_version', 'notes', 'applied_on', 'due_date'):
            if key in app:
                _text(app[key], key)
        validate_url(app.get('url', ''))
        validate_date(app.get('applied_on', ''))
        validate_date(app.get('due_date', ''))
        evidence = _items(app, 'evidence', 100)
        for item in evidence:
            for key in ('kind', 'message_id', 'thread_id', 'url', 'recipient', 'detail'):
                if key in item:
                    _text(item[key], key)
            validate_url(item.get('url', ''))
        if app['status'] == 'SENT' and not any(e.get('kind') == 'submission' and (e.get('message_id') or e.get('url')) for e in evidence):
            raise ValueError('SENT requires submission evidence, not just a proposed application.')
        progressed=('EMPLOYER-ACKNOWLEDGED','REPLIED','INTERVIEW','REJECTED','WITHDRAWN')
        if app['status'] in progressed and not any(e.get('kind') in ('submission','acknowledgement','outcome','reply','interview') and (e.get('message_id') or e.get('url')) for e in evidence):
            raise ValueError('Progressed applications require submission or outcome evidence.')
    names = set()
    for fact in _items(report, 'profile', 200):
        name = _text(fact.get('name'), 'Profile name', 250)
        _text(fact.get('value'), 'Profile value')
        _text(fact.get('source', ''), 'Profile source')
        if not name or name in names or fact.get('state') not in FACT_STATES:
            raise ValueError('Invalid/duplicate profile field or confirmation state.')
        names.add(name)
    for doc in _items(report, 'documents', 200):
        for key in ('document_key', 'filename', 'sha256'):
            if not _text(doc.get(key), key, 1000):
                raise ValueError('Document ' + key + ' is required.')
        if not re.fullmatch(r'[a-fA-F0-9]{64}', doc['sha256']) or doc.get('state') not in DOC_STATES:
            raise ValueError('Each document needs its exact SHA-256 and a valid review state.')
        _text(doc.get('source', ''), 'Document source')
        if doc.get('application_external_id', '') not in seen | {''}:
            raise ValueError('Document refers to an application absent from this report.')
    if 'session' in report:
        session=report['session']
        if not isinstance(session,dict):raise ValueError('Invalid session record.')
        for field in ('started_at','completed_at'):
            value=_text(session.get(field),field,100)
            parsed=parse_time(value)
            if parsed.tzinfo is None:raise ValueError('Session timestamps need their UTC offset.')
        if parse_time(session['completed_at']) < parse_time(session['started_at']):
            raise ValueError('Session completion precedes its start.')
        _text(session.get('title','Imported job-search session'),'Session title',250)
        _text(session.get('check_detail',''),'Session check detail')
    return report


def cancelled(stop):
    if stop is not None and stop.is_set():raise ValueError('CANCELLED — local operation stopped; no incomplete import is committed.')


def load_report(path, stop=None):
    cancelled(stop)
    path = Path(path)
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('Report exceeds the 5 MiB limit; split it into smaller sessions.')
    raw = path.read_bytes()
    cancelled(stop)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('Report grew beyond the supported size limit.')
    try:
        report = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('Not a valid UTF-8 JSON report. Export the structured workflow report, not the Markdown ledger.') from None
    return validate_report(report), hashlib.sha256(raw).hexdigest()


def report_summary(report):
    counts = {}
    for app in report.get('applications', []):
        counts[app['status']] = counts.get(app['status'], 0) + 1
    return ', '.join(f'{count} {state}' for state, count in sorted(counts.items())) or 'No applications'


def import_report(conn, report, digest, source_file='', stop=None, progress=lambda _:None):
    """One transaction, stable IDs, append-only evidence and local-edit protection."""
    validate_report(report)
    cancelled(stop)
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Missing report digest.')
    if conn.execute('SELECT 1 FROM workflow_reports WHERE report_id=? AND digest=?', (report['report_id'], digest)).fetchone():
        return {'created': 0, 'updated': 0, 'preserved': 0, 'duplicate': True}
    result = {'created': 0, 'updated': 0, 'preserved': 0, 'duplicate': False}
    stamp = timestamp()
    account = report['account'].casefold()
    namespace = account + '|' + report['namespace'] + ':'
    # Do not call core.add_application here: its own context would commit a partial import.
    with conn:
        for item in report.get('applications', []):
            cancelled(stop)
            progress('Importing application '+item['external_id'])
            key = namespace + item['external_id']
            fields = {name: item[name] for name in ('title', 'employer', 'area', 'url', 'cv_version', 'due_date', 'notes', 'applied_on') if name in item}
            fields['status'] = STATES[item['status']]
            link = conn.execute('SELECT * FROM workflow_links WHERE source_id=?', (key,)).fetchone()
            row = conn.execute('SELECT * FROM applications WHERE id=?', (link['application_id'],)).fetchone() if link else None
            if row is None and fields.get('url'):
                candidates = conn.execute('SELECT * FROM applications WHERE title=? AND employer=? AND url=?',
                                          (fields['title'], fields['employer'], fields['url'])).fetchall()
                if len(candidates) == 1:
                    row = candidates[0]
            if row is None:
                names = list(fields)
                cur = conn.execute('INSERT INTO applications (' + ','.join(names) + ',created_at,updated_at) VALUES (' + ','.join('?' for _ in names) + ',?,?)',
                                   [fields[k] for k in names] + [stamp, stamp])
                app_id = cur.lastrowid
                result['created'] += 1
                log(conn, 'application', app_id, 'workflow import', key)
            else:
                app_id = row['id']
                previous = json.loads(link['baseline_json']) if link else {}
                changes = {}
                for name, value in fields.items():
                    if value == row[name]:
                        continue
                    if not row[name] or (name in previous and row[name] == previous[name]):
                        changes[name] = value
                    else:
                        result['preserved'] += 1
                if changes:
                    conn.execute('UPDATE applications SET ' + ','.join(k + '=?' for k in changes) + ',updated_at=? WHERE id=?',
                                 [*changes.values(), stamp, app_id])
                    result['updated'] += 1
                    log(conn, 'application', app_id, 'workflow update', ', '.join(changes))
            baseline = {**(json.loads(link['baseline_json']) if link else {}), **fields}
            conn.execute('INSERT INTO workflow_links VALUES (?,?,?) ON CONFLICT(source_id) DO UPDATE SET application_id=excluded.application_id,baseline_json=excluded.baseline_json',
                         (key, app_id, json.dumps(baseline)))
            for evidence in item.get('evidence', []):
                cancelled(stop)
                payload = json.dumps(evidence, sort_keys=True)
                evidence_id = hashlib.sha256(payload.encode()).hexdigest()
                conn.execute('INSERT OR IGNORE INTO workflow_evidence VALUES (?,?,?,?,?)', (key, evidence_id, app_id, payload, stamp))
                if evidence.get('thread_id'):
                    conn.execute('INSERT OR IGNORE INTO mail_bindings VALUES (?,?,?)', (account, evidence['thread_id'], app_id))
        for fact in report.get('profile', []):
            cancelled(stop)
            old = conn.execute('SELECT * FROM workflow_facts WHERE name=?', (fact['name'],)).fetchone()
            source = fact.get('source', '') or report['report_id']
            if old and old['source'].startswith('Local edit'):
                result['preserved'] += 1
                continue
            conn.execute('INSERT INTO workflow_facts VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,state=excluded.state,source=excluded.source,updated_at=excluded.updated_at',
                         (fact['name'], fact['value'], fact['state'], source, stamp))
        for doc in report.get('documents', []):
            cancelled(stop)
            key = namespace + doc['document_key']
            sha = doc['sha256'].lower()
            old = conn.execute('SELECT * FROM workflow_documents WHERE document_key=? AND sha256=?', (key, sha)).fetchone()
            if old and old['source'].startswith('Local edit'):
                result['preserved'] += 1
                continue
            app_key = namespace + doc['application_external_id'] if doc.get('application_external_id') else ''
            conn.execute('INSERT INTO workflow_documents(document_key,sha256,filename,state,source,source_id,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(document_key,sha256) DO UPDATE SET filename=excluded.filename,state=excluded.state,source=excluded.source,source_id=excluded.source_id,updated_at=excluded.updated_at',
                         (key, sha, doc['filename'], doc['state'], doc.get('source', '') or report['report_id'], app_key, stamp))
        if report.get('session'):
            session=report['session']
            detail='Imported historical report; not a fresh app check. '+session.get('check_detail','No mail-check result supplied.')
            conn.execute("INSERT INTO workflow_sessions(id,title,started_at,completed_at,state,check_state,check_detail) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET check_detail=excluded.check_detail",
                ('import:'+namespace+report['report_id'],session.get('title','Imported job-search session'),session['started_at'],session['completed_at'],'RECORDED','REPORTED',detail))
        cancelled(stop)
        conn.execute('INSERT INTO workflow_reports VALUES (?,?,?,?,?)', (report['report_id'], digest, stamp, Path(source_file).name, report_summary(report)))
    return result


def save_fact(conn, name, value, state):
    name = _text(name, 'Field name', 250)
    value = _text(value, 'Field value')
    if not name or state not in FACT_STATES:
        raise ValueError('Enter a field name and confirmation state.')
    with conn:
        conn.execute('INSERT INTO workflow_facts VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,state=excluded.state,source=excluded.source,updated_at=excluded.updated_at',
                     (name, value, state, 'Local edit / candidate review', timestamp()))


def file_digest(path, stop=None):
    sha = hashlib.sha256()
    with Path(path).open('rb') as fp:
        for block in iter(lambda: fp.read(1024 * 1024), b''):
            cancelled(stop)
            sha.update(block)
    return sha.hexdigest()


def link_document(conn, document_key, path, source_id='', stop=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Choose a local document file.')
    sha = file_digest(path,stop)
    cancelled(stop)
    with conn:
        conn.execute('INSERT INTO workflow_documents VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(document_key,sha256) DO UPDATE SET local_path=excluded.local_path,updated_at=excluded.updated_at',
                     (document_key, sha, path.name, 'REVIEW REQUIRED', 'Local edit / selected file', source_id, str(path), timestamp()))
    return sha


def approve_document(conn, key, sha, stop=None):
    row = conn.execute('SELECT * FROM workflow_documents WHERE document_key=? AND sha256=?', (key, sha)).fetchone()
    if not row or not row['local_path']:
        raise ValueError('Link and review the local file before approving its contents.')
    if file_digest(row['local_path'],stop) != sha:
        raise ValueError('The file has changed. Link its new revision and review it again.')
    if row['state'] == 'SENT':
        raise ValueError('This revision is already recorded as sent; its history is retained.')
    cancelled(stop)
    with conn:
        conn.execute("UPDATE workflow_documents SET state='APPROVED',source='Local edit / candidate approval',updated_at=? WHERE document_key=? AND sha256=?", (timestamp(), key, sha))


def start_session(conn, title='Job-search session', at=None):
    if conn.execute("SELECT 1 FROM workflow_sessions WHERE state='ACTIVE'").fetchone():
        raise ValueError('Finish the active session before starting another.')
    ident = uuid.uuid4().hex
    with conn:
        conn.execute('INSERT INTO workflow_sessions(id,title,started_at,state) VALUES (?,?,?,?)', (ident, title.strip() or 'Job-search session', timestamp(at), 'ACTIVE'))
    return ident


def complete_session(conn, ident, at=None):
    at = at or utcnow()
    row=conn.execute('SELECT started_at FROM workflow_sessions WHERE id=?',(ident,)).fetchone()
    if row and at.astimezone(timezone.utc) < parse_time(row['started_at']):
        raise ValueError('The clock is earlier than the session start. Correct the clock before completing the session.')
    with conn:
        cur = conn.execute("UPDATE workflow_sessions SET state='COMPLETED',completed_at=?,check_due=?,check_state='PENDING',check_detail='Waiting five minutes; app must be open.' WHERE id=? AND state='ACTIVE'",
                           (timestamp(at), timestamp(at + timedelta(minutes=5)), ident))
        if cur.rowcount != 1:
            raise ValueError('Select the active session. A completed session cannot be completed twice.')


def retry_check(conn, ident):
    with conn:
        cur = conn.execute("UPDATE workflow_sessions SET check_state='PENDING',check_detail='Retry requested; waiting for Gmail availability.' WHERE id=? AND state='COMPLETED' AND check_state IN ('BLOCKED','FAILED','CANCELLED','UNKNOWN','PARTIAL')", (ident,))
        if cur.rowcount != 1:
            raise ValueError('Only an incomplete/failed completed-session check can be retried.')


def due_check(conn, at=None):
    return conn.execute("SELECT * FROM workflow_sessions WHERE state='COMPLETED' AND check_state='PENDING' AND check_due<=? ORDER BY check_due LIMIT 1", (timestamp(at),)).fetchone()


def check_result(conn, ident, state, detail, run_id=''):
    if state not in ('RUNNING', 'PASS', 'PARTIAL', 'FAILED', 'CANCELLED', 'BLOCKED', 'UNKNOWN'):
        raise ValueError('Invalid check outcome.')
    with conn:
        conn.execute('UPDATE workflow_sessions SET check_state=?,check_detail=?,mail_run_id=? WHERE id=?', (state, detail[:4000], run_id, ident))
