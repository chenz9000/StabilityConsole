"""Read-only Gmail collection, local evidence, and app-lifetime scheduling."""
from __future__ import annotations
import base64
import ctypes
import hashlib
import html
import json
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
DEFAULTS = {'enabled': False, 'interval_minutes': 5, 'lookback_days': 180, 'browser': 'msedge', 'enrich': True}

class SyncError(Exception):
    """Actionable errors that contain no message bodies or credentials."""


class PageTokenError(SyncError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('wb') as f:
            os.chmod(temp, 0o600)
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def protect(value, decrypt=False):
    if os.name != 'nt':
        raise SyncError('Gmail token storage requires Windows DPAPI. Offline tracking remains available.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buf = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    lib = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = lib.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        fn = lib.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), 'StabilityConsole Gmail', None, None, None, 1, ctypes.byref(result))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise SyncError('Windows could not protect/unlock Gmail authorization. Reconnect Gmail under the same Windows user.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def import_client(root, source):
    if os.name != 'nt':
        raise SyncError('Desktop Gmail authorization is supported on Windows only.')
    raw = Path(source).read_bytes()
    if len(raw) > 64000:
        raise SyncError('OAuth client file is too large.')
    config = json.loads(raw)
    installed = config.get('installed', {})
    if not installed.get('client_id', '').endswith('.apps.googleusercontent.com') or installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or installed.get('token_uri') != 'https://oauth2.googleapis.com/token':
        raise SyncError('Choose the downloaded Google OAuth Desktop app JSON, not a web app or service-account key.')
    if 'http://localhost' not in installed.get('redirect_uris', []) and 'http://127.0.0.1' not in installed.get('redirect_uris', []):
        raise SyncError('Desktop OAuth client must support a loopback redirect.')
    atomic_write(Path(root) / 'gmail-client.dpapi', protect(raw))
    # A changed client requires a fresh consent; cached messages and tracking remain intact.
    (Path(root) / 'gmail-token.dpapi').unlink(missing_ok=True)


def credentials(root, interactive=False):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SyncError('Install integration support using the Gmail tab, then restart with Launch-StabilityConsole.bat.') from None
    root = Path(root)
    token = root / 'gmail-token.dpapi'
    creds = None
    if token.exists() and not interactive:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(protect(token.read_bytes(), True)), [SCOPE])
            # Never retain accidentally imported broader permissions.
            if set(creds.scopes or ()) != {SCOPE}:
                raise SyncError('Stored Gmail scope is not read-only. Reconnect Gmail.')
            if not creds.valid and creds.refresh_token:
                transport = GoogleRequest()
                creds.refresh(lambda *a, **kw: transport(*a, **{**kw, 'timeout': 20}))
        except SyncError:
            raise
        except Exception:
            raise SyncError('Gmail authorization expired or was revoked. Reconnect Gmail; previous evidence is retained.') from None
    if interactive:
        if not (root / 'gmail-client.dpapi').exists():
            raise SyncError('First import a Google OAuth Desktop app client JSON using the Gmail tab.')
        config = json.loads(protect((root / 'gmail-client.dpapi').read_bytes(), True))
        try:
            flow = InstalledAppFlow.from_client_config(config, [SCOPE], autogenerate_code_verifier=True)
            creds = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True,
                                         timeout_seconds=120, access_type='offline', prompt='consent',
                                         authorization_prompt_message='', success_message='StabilityConsole Gmail authorization received. Return to the app.')
        except Exception:
            raise SyncError('Gmail sign-in was cancelled, blocked, or timed out. Check Desktop OAuth client, Gmail API and test-user settings, then Connect again.') from None
    if not creds or not creds.valid:
        raise SyncError('Gmail is not connected. Choose Connect Gmail in the Gmail tab.')
    granted = set(creds.granted_scopes or creds.scopes or ())
    if granted != {SCOPE}:
        raise SyncError('Expected read-only Gmail consent was not granted. Reconnect Gmail.')
    atomic_write(token, protect(creds.to_json().encode()))
    return creds


class GmailClient:
    def __init__(self, creds):
        self.creds = creds

    def get(self, resource, params=None):
        url = 'https://gmail.googleapis.com/gmail/v1/users/me/' + resource
        if params:
            url += '?' + urlencode(params)
        try:
            with urlopen(Request(url, headers={'Authorization': 'Bearer ' + self.creds.token}), timeout=20) as response:
                data = response.read(5_000_001)
                if len(data) > 5_000_000:
                    raise SyncError('Gmail response exceeded the safe size limit. Narrow the matching query.')
                return json.loads(data)
        except HTTPError as e:
            if e.code == 400 and params and params.get('pageToken'):
                raise PageTokenError('Gmail pagination checkpoint was rejected. It has been cleared; the next sync restarts from the last completed checkpoint without duplicating saved messages.') from None
            if e.code == 401:
                raise SyncError('Gmail returned 401. Reconnect Gmail.') from None
            if e.code == 403:
                raise SyncError('Gmail returned 403. Check Gmail API enablement, read-only scope, OAuth audience/test user and Google account policy.') from None
            if e.code == 429 or e.code >= 500:
                raise SyncError('Gmail is rate-limited or temporarily unavailable. Paused; retry after the next configured interval.') from None
            raise SyncError('Gmail request failed: HTTP ' + str(e.code) + '. No successful-sync timestamp was recorded.') from None
        except (URLError, TimeoutError, OSError):
            raise SyncError('Gmail could not be reached. Check internet, DNS, proxy/firewall and retry. Old messages are historical evidence.') from None


def init_mail(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS mail_messages (
      account TEXT NOT NULL, message_id TEXT NOT NULL, thread_id TEXT NOT NULL,
      sender TEXT NOT NULL, subject TEXT NOT NULL, received_at TEXT NOT NULL,
      body TEXT NOT NULL, links_json TEXT NOT NULL, collected_at TEXT NOT NULL,
      PRIMARY KEY(account,message_id));
    CREATE TABLE IF NOT EXISTS mail_matches (
      account TEXT NOT NULL, message_id TEXT NOT NULL, application_id INTEGER NOT NULL,
      evidence TEXT NOT NULL, confidence TEXT NOT NULL, suggested_status TEXT NOT NULL DEFAULT '',
      review_state TEXT NOT NULL DEFAULT 'Pending', proposal_json TEXT NOT NULL DEFAULT '{}',
      lookup_state TEXT NOT NULL DEFAULT 'Not requested', PRIMARY KEY(account,message_id,application_id));
    CREATE TABLE IF NOT EXISTS mail_bindings (
      account TEXT NOT NULL, thread_id TEXT NOT NULL, application_id INTEGER NOT NULL,
      PRIMARY KEY(account,thread_id,application_id));
    CREATE TABLE IF NOT EXISTS mail_cursors (
      account TEXT NOT NULL, application_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
      query TEXT NOT NULL, page_token TEXT NOT NULL DEFAULT '', completed_at INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(account,application_id));
    CREATE TABLE IF NOT EXISTS mail_runs (
      run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '',
      outcome TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
    ''')
    conn.commit()


def read_settings(root):
    path = Path(root) / 'gmail-settings.json'
    if not path.exists():
        return DEFAULTS.copy()
    try:
        value = {**DEFAULTS, **json.loads(path.read_text('utf-8'))}
        value['interval_minutes'] = max(1, min(120, int(value['interval_minutes'])))
        value['lookback_days'] = max(1, min(3650, int(value['lookback_days'])))
        if value['browser'] not in ('msedge', 'chrome'):
            raise ValueError()
        return value
    except Exception:
        raise SyncError('Gmail settings could not be read. Open Settings and save valid settings; automatic sync is stopped.') from None


def save_settings(root, value):
    settings = {**DEFAULTS, **value}
    if not 1 <= int(settings['interval_minutes']) <= 120:
        raise ValueError('Sync interval must be between 1 and 120 minutes.')
    if not 1 <= int(settings['lookback_days']) <= 3650:
        raise ValueError('Initial lookback must be between 1 and 3650 days.')
    if settings['browser'] not in ('msedge', 'chrome'):
        raise ValueError('Select Edge or Chrome.')
    atomic_write(Path(root) / 'gmail-settings.json', json.dumps(settings).encode())


class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.text = []; self.links = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'): self.hidden += 1
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if href.startswith('https://'): self.links.append(href)
    def handle_endtag(self, tag):
        if tag in ('style', 'script'): self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden: self.text.append(data)


def decode_message(raw):
    headers = {h['name'].lower(): h['value'] for h in raw.get('payload', {}).get('headers', [])}
    texts, links = [], []
    def walk(part):
        if part.get('filename'): return  # Never download attachments.
        encoded = part.get('body', {}).get('data')
        if encoded and part.get('mimeType') in ('text/plain', 'text/html'):
            data = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8', 'replace')
            if part['mimeType'] == 'text/html':
                parser = BodyParser(); parser.feed(data); texts.append(' '.join(parser.text)); links.extend(parser.links)
            else:
                texts.append(data); links.extend(re.findall(r'https://[^\s<>"\)]+', data))
        for child in part.get('parts', []): walk(child)
    walk(raw.get('payload', {}))
    body = re.sub(r'\s+', ' ', html.unescape(' '.join(texts))).strip()[:40000]
    return {'message_id': raw['id'], 'thread_id': raw['threadId'], 'sender': headers.get('from', ''),
            'subject': headers.get('subject', ''), 'received_at': headers.get('date', 'UNKNOWN'),
            'body': body, 'links': list(dict.fromkeys(links))[:40]}


def normal(s):
    return ' '.join(re.findall(r'\w+', str(s).casefold()))


def match_message(app, message, bound=False):
    combined = normal(message['subject'] + ' ' + message['body'])
    title = normal(app['title'])
    employer = normal(app['employer'])
    title_match = bool(title and title in combined)
    employer_match = bool(employer and employer in combined)
    if not bound and not title_match:
        return None
    confidence = 'Confirmed thread' if bound else 'Corroborated' if employer_match else 'Tentative title only'
    evidence = 'Previously linked Gmail thread' if bound else 'Entered title occurs in message' + ('; employer also occurs' if employer_match else '; employer/application identity needs review')
    suggested = ''
    # These remain suggestions. Quoted history, negation and generic emails require human review.
    for status, words in [('Rejected', ('not been successful', 'not be moving forward', 'unsuccessful', 'regret to inform')),
                          ('Interview scheduled', ('interview invitation', 'invite you to an interview', 'interview scheduled')),
                          ('Acknowledged', ('application received', 'received your application', 'thank you for applying'))]:
        if any(w in combined for w in words): suggested = status; break
    return confidence, evidence, suggested


def sync_mail(conn, client, settings, stop, progress=lambda s: None):
    init_mail(conn)
    run = uuid.uuid4().hex
    conn.execute('INSERT INTO mail_runs(run_id,started_at,outcome) VALUES (?,?,?)', (run, stamp(), 'RUNNING'))
    conn.commit()
    try:
        account = client.get('profile')['emailAddress'].casefold()
        if settings.get('account') and account != settings['account'].casefold():
            raise SyncError('Connected Gmail account differs from the selected account. Reconnect the intended account before syncing.')
        apps = [dict(r) for r in conn.execute('SELECT * FROM applications ORDER BY id')]
        new = matches = pending_pages = 0
        for app in apps:
            if stop.is_set(): raise SyncError('CANCELLED: Sync stopped; completed pages remain deduplicated. Resume with Sync now.')
            progress('Checking Gmail for application #' + str(app['id']))
            title = app['title'].replace('"', ' ').strip()
            fingerprint = hashlib.sha256((title + '|' + app['employer'] + '|' + str(settings['lookback_days'])).encode()).hexdigest()
            cursor = conn.execute('SELECT * FROM mail_cursors WHERE account=? AND application_id=?', (account, app['id'])).fetchone()
            threads = [r[0] for r in conn.execute('SELECT thread_id FROM mail_bindings WHERE account=? AND application_id=?', (account, app['id']))]
            query = '-in:spam -in:trash "' + title + '"'
            if cursor and cursor['fingerprint'] == fingerprint and cursor['page_token']:
                query, token = cursor['query'], cursor['page_token']
            else:
                after = max(0, int(cursor['completed_at']) - 86400) if cursor and cursor['fingerprint'] == fingerprint and cursor['completed_at'] else int(time.time()) - int(settings['lookback_days']) * 86400
                query += ' after:' + str(after)
                token = ''
            cycle_start = int(re.search(r' before:(\d+)', query).group(1)) if re.search(r' before:(\d+)', query) else int(time.time())
            if ' before:' not in query: query += ' before:' + str(cycle_start)
            # Per-application pagination continues next cycle if the budget is reached.
            for page in range(10):
                if stop.is_set(): raise SyncError('CANCELLED: Sync stopped. Resume with Sync now.')
                params = {'q': query, 'maxResults': 50}
                if token: params['pageToken'] = token
                try:
                    listing = client.get('messages', params)
                except PageTokenError:
                    with conn: conn.execute("UPDATE mail_cursors SET page_token='' WHERE account=? AND application_id=?",(account,app['id']))
                    raise
                except SyncError:
                    raise
                for item in listing.get('messages', []):
                    if stop.is_set(): raise SyncError('CANCELLED: Sync stopped. Resume with Sync now.')
                    cached = conn.execute('SELECT * FROM mail_messages WHERE account=? AND message_id=?', (account, item['id'])).fetchone()
                    if cached:
                        msg = dict(cached); msg['links'] = json.loads(msg['links_json'])
                    else:
                        msg = decode_message(client.get('messages/' + item['id'], {'format': 'full'}))
                    result = match_message(app, msg, msg['thread_id'] in threads)
                    if not result: continue
                    with conn:
                        changed = conn.execute('INSERT OR IGNORE INTO mail_messages VALUES (?,?,?,?,?,?,?,?,?)',
                            (account, msg['message_id'], msg['thread_id'], msg['sender'], msg['subject'], msg['received_at'], msg['body'], json.dumps(msg['links']), stamp())).rowcount
                        new += changed
                        matches += conn.execute('INSERT OR IGNORE INTO mail_matches(account,message_id,application_id,evidence,confidence,suggested_status) VALUES (?,?,?,?,?,?)',
                            (account, msg['message_id'], app['id'], result[1], result[0], result[2])).rowcount
                token = listing.get('nextPageToken', '')
                with conn:
                    conn.execute('INSERT INTO mail_cursors VALUES (?,?,?,?,?,?) ON CONFLICT(account,application_id) DO UPDATE SET fingerprint=excluded.fingerprint,query=excluded.query,page_token=excluded.page_token,completed_at=excluded.completed_at',
                        (account, app['id'], fingerprint, query, token, cycle_start if not token else (cursor['completed_at'] if cursor else 0)))
                if not token: break
            if token: pending_pages += 1
            # A reviewed thread may have subsequent replies that omit the job title entirely.
            for thread in threads:
                if stop.is_set(): raise SyncError('CANCELLED: Sync stopped.')
                for ref in client.get('threads/' + thread, {'format': 'minimal'}).get('messages', []):
                    if stop.is_set(): raise SyncError('CANCELLED: Sync stopped.')
                    if conn.execute('SELECT 1 FROM mail_matches WHERE account=? AND message_id=? AND application_id=?',(account,ref['id'],app['id'])).fetchone(): continue
                    cached=conn.execute('SELECT * FROM mail_messages WHERE account=? AND message_id=?',(account,ref['id'])).fetchone()
                    if cached:
                        msg=dict(cached);msg['links']=json.loads(msg['links_json'])
                    else: msg=decode_message(client.get('messages/' + ref['id'], {'format':'full'}))
                    result = match_message(app, msg, True)
                    with conn:
                        new += conn.execute('INSERT OR IGNORE INTO mail_messages VALUES (?,?,?,?,?,?,?,?,?)',
                            (account, msg['message_id'], msg['thread_id'], msg['sender'], msg['subject'], msg['received_at'], msg['body'], json.dumps(msg['links']), stamp())).rowcount
                        matches += conn.execute('INSERT OR IGNORE INTO mail_matches(account,message_id,application_id,evidence,confidence,suggested_status) VALUES (?,?,?,?,?,?)',
                            (account, msg['message_id'], app['id'], result[1], result[0], result[2])).rowcount
        detail = f'{new} new relevant messages; {matches} new application matches. Account: {account}'
        if pending_pages: detail='PARTIAL — '+detail+f'; {pending_pages} application(s) have more pages pending next cycle.'
        with conn: conn.execute('UPDATE mail_runs SET finished_at=?,outcome=?,detail=? WHERE run_id=?', (stamp(), 'PARTIAL' if pending_pages else 'PASS', detail, run))
        return detail
    except Exception as exc:
        safe = str(exc) if isinstance(exc, SyncError) else 'Sync failed at collection/storage stage. No successful-sync timestamp recorded. Retry or reconnect.'
        with conn: conn.execute('UPDATE mail_runs SET finished_at=?,outcome=?,detail=? WHERE run_id=?', (stamp(), 'CANCELLED' if stop.is_set() else 'FAILED', safe, run))
        raise SyncError(safe) from None


class AppWorker:
    """One daemon worker per window: no Tk calls and no overlapping network runs."""
    def __init__(self):
        self.events = queue.Queue(); self.stop = threading.Event(); self.lock = threading.Lock(); self.thread = None
    @property
    def busy(self): return self.lock.locked()
    def start(self, work):
        if not self.lock.acquire(False): return False
        self.stop.clear()
        def run():
            try:
                self.events.put(('done', work(self.stop, lambda s: self.events.put(('progress', s)))))
            except Exception as exc:
                self.events.put(('error', str(exc) if isinstance(exc, (SyncError, ValueError)) else 'Operation failed. Check setup, network and source access; no success is claimed.'))
            finally:
                self.lock.release()
        self.thread = threading.Thread(target=run, daemon=True, name='StabilityConsoleSync'); self.thread.start(); return True
    def cancel(self): self.stop.set()
    def close(self): self.stop.set()
