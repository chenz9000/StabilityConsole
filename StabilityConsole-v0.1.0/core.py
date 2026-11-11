"""Stability Console: offline source of truth. Python standard library only."""
from __future__ import annotations
import csv
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

VERSION = '0.2.0'
STATUSES = ('Discovered', 'Saved', 'Preparing', 'Applied', 'Acknowledged', 'Replied', 'Interview scheduled', 'Interviewed', 'Offer', 'Rejected', 'Withdrawn', 'Expired', 'Unknown')
PRIORITIES = ('Urgent', 'High', 'Normal', 'Low')

def data_dir():
    root = os.environ.get('STABILITY_CONSOLE_DATA')
    if not root:
        root = str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'StabilityConsole')
    return Path(root)

def validate_date(value):
    if value:
        date.fromisoformat(value)
    return value

def validate_url(value):
    if not value:
        return ''
    p = urlparse(value.strip())
    if p.scheme not in ('http','https') or not p.netloc:
        raise ValueError('Use a full https:// or http:// URL')
    return value.strip()

def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, employer TEXT NOT NULL DEFAULT '',
        area TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Discovered',
        cv_version TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        applied_on TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Personal',
        priority TEXT NOT NULL DEFAULT 'Normal', due_date TEXT NOT NULL DEFAULT '',
        done INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, object_type TEXT NOT NULL, object_id INTEGER NOT NULL,
        action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', at TEXT NOT NULL
      );
    ''')
    return conn

def now(): return datetime.now().astimezone().isoformat(timespec='seconds')

def add_application(conn, title, employer='', area='', url='', status='Discovered', cv_version='', due_date='', notes='', applied_on=''):
    if not title.strip(): raise ValueError('Job title is required')
    if status not in STATUSES: raise ValueError('Invalid status')
    validate_date(due_date); validate_date(applied_on); url=validate_url(url)
    stamp=now()
    with conn:
        cur=conn.execute('''INSERT INTO applications (title,employer,area,url,status,cv_version,due_date,notes,applied_on,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(title.strip(),employer.strip(),area.strip(),url,status,cv_version.strip(),due_date,notes,applied_on,stamp,stamp))
        log(conn,'application',cur.lastrowid,'created',status)
    return cur.lastrowid

def update_application(conn, ident, **updates):
    allowed={'title','employer','area','url','status','cv_version','due_date','notes','applied_on'}
    updates={k:v for k,v in updates.items() if k in allowed}
    if not updates: return
    if 'title' in updates and not updates['title'].strip(): raise ValueError('Job title is required')
    if 'status' in updates and updates['status'] not in STATUSES: raise ValueError('Invalid status')
    for field in ('due_date','applied_on'):
        if field in updates: validate_date(updates[field])
    if 'url' in updates: updates['url']=validate_url(updates['url'])
    old=conn.execute('SELECT * FROM applications WHERE id=?',(ident,)).fetchone()
    if old is None: raise ValueError('Application no longer exists')
    updates['updated_at']=now()
    with conn:
        conn.execute('UPDATE applications SET '+', '.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),ident))
        if 'status' in updates and old['status']!=updates['status']:
            log(conn,'application',ident,'status',old['status']+' -> '+updates['status'])
        else: log(conn,'application',ident,'updated','details edited')

def add_task(conn,title,category='Personal',priority='Normal',due_date='',notes=''):
    if not title.strip(): raise ValueError('Task title is required')
    if priority not in PRIORITIES: raise ValueError('Invalid priority')
    validate_date(due_date);stamp=now()
    with conn:
        cur=conn.execute('INSERT INTO tasks (title,category,priority,due_date,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?)', (title.strip(),category.strip(),priority,due_date,notes,stamp,stamp))
        log(conn,'task',cur.lastrowid,'created',title)
    return cur.lastrowid

def set_task_done(conn, ident, done):
    with conn:
        cur=conn.execute('UPDATE tasks SET done=?,updated_at=? WHERE id=?',(int(bool(done)),now(),ident))
        if cur.rowcount==0: raise ValueError('Task no longer exists')
        log(conn,'task',ident,'completed' if done else 'reopened')

def log(conn,kind,ident,action,details=''):
    conn.execute('INSERT INTO events (object_type,object_id,action,details,at) VALUES (?,?,?,?,?)',(kind,ident,action,details,now()))

def applications(conn,needle=''):
    if needle:
        term='%'+needle.strip()+'%'
        return conn.execute('SELECT * FROM applications WHERE title LIKE ? OR employer LIKE ? OR area LIKE ? OR status LIKE ? ORDER BY updated_at DESC,id DESC',(term,term,term,term)).fetchall()
    return conn.execute('SELECT * FROM applications ORDER BY updated_at DESC,id DESC').fetchall()

def tasks(conn,show_done=False):
    q='SELECT * FROM tasks'+('' if show_done else ' WHERE done=0')+" ORDER BY CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date ASC, CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Normal' THEN 2 ELSE 3 END, id DESC"
    return conn.execute(q).fetchall()

def due_items(conn):
    today=date.today().isoformat()
    t=conn.execute("SELECT * FROM tasks WHERE done=0 AND due_date<>'' AND due_date<=? ORDER BY due_date",(today,)).fetchall()
    a=conn.execute("SELECT * FROM applications WHERE due_date<>'' AND due_date<=? AND status NOT IN ('Rejected','Withdrawn','Expired','Offer') ORDER BY due_date",(today,)).fetchall()
    return t,a

def metrics(conn):
    all_app=conn.execute('SELECT status,COUNT(*) count FROM applications GROUP BY status').fetchall()
    counts={r['status']:r['count'] for r in all_app}
    open_tasks=conn.execute('SELECT COUNT(*) FROM tasks WHERE done=0').fetchone()[0]
    return {'total':sum(counts.values()),'applied':counts.get('Applied',0)+counts.get('Acknowledged',0)+counts.get('Replied',0)+counts.get('Interview scheduled',0)+counts.get('Interviewed',0)+counts.get('Offer',0)+counts.get('Rejected',0),'interviews':counts.get('Interview scheduled',0)+counts.get('Interviewed',0),'tasks':open_tasks}

def search_urls(areas,keywords=''):
    # Browser searches, not scrape claims. No network request is performed here.
    area_list=[]
    for area in re.split(r'[,;\n]+',areas):
        area=area.strip()
        if area and area.casefold() not in [a.casefold() for a in area_list]: area_list.append(area)
    if not area_list: raise ValueError('Enter at least one area')
    terms=keywords.strip()
    links=[]
    for area in area_list:
        q=f'{terms} jobs vacancies employment "{area}" South Africa'.strip()
        links.append((area,'Google web search','https://www.google.com/search?'+urlencode({'q':q})))
        links.append((area,'Indeed South Africa','https://za.indeed.com/jobs?'+urlencode({'q':terms,'l':area})))
    return links

def export_csv(conn,path):
    columns=['id','title','employer','area','url','status','cv_version','due_date','notes','applied_on','created_at','updated_at']
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Atomic replace: no partially written exports.
    handle,tmp=tempfile.mkstemp(prefix='sc-',suffix='.csv',dir=str(path.parent),text=True)
    try:
        with os.fdopen(handle,'w',encoding='utf-8-sig',newline='') as fp:
            writer=csv.writer(fp);writer.writerow(columns)
            for row in applications(conn):writer.writerow([row[c] for c in columns])
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path

def backup(conn,destination):
    dest=sqlite3.connect(str(destination))
    try: conn.backup(dest)
    finally:dest.close()

def preflight(root):
    outcomes=[]
    import sys
    outcomes.append(('PASS' if sys.version_info >= (3,10) else 'FAIL','Python version',sys.version.split()[0]))
    try:
        root.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root,delete=True) as fp: fp.write(b'check');fp.flush()
        outcomes.append(('PASS','Writable data directory',str(root)))
    except OSError as exc:outcomes.append(('FAIL','Writable data directory',str(exc)))
    try:
        import tkinter
        outcomes.append(('PASS','Tkinter',str(tkinter.TkVersion)))
    except ImportError:outcomes.append(('FAIL','Tkinter','Install Python with Tcl/Tk support'))
    return outcomes

