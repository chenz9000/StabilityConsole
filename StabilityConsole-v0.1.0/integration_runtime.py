"""Local-only install/bootstrap and owned browser subprocess cleanup."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import venv
from mail_sync import SyncError, atomic_write

HERE = Path(__file__).resolve().parent


def requirements_hash():
    return hashlib.sha256((HERE / 'requirements-integrations.txt').read_bytes()).hexdigest()


def runtime_paths(root):
    v = Path(root) / 'integration-runtime'
    return v, v / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def runtime_ready(root):
    v, python = runtime_paths(root)
    try:
        return python.exists() and (v/'installed.sha256').read_text().strip() == requirements_hash()
    except OSError: return False


def install_runtime(root, stop, progress, worker=None):
    v, python = runtime_paths(root)
    progress('Creating/reusing local integration runtime…')
    if not python.exists(): venv.EnvBuilder(with_pip=True).create(v)
    if stop.is_set(): raise SyncError('Setup cancelled. Reopen setup to resume.')
    (v/'installed.sha256').unlink(missing_ok=True)
    progress('Installing pinned Gmail/browser libraries; no browser binaries are downloaded…')
    cmd = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--retries', '1', '--timeout', '20', '-r', str(HERE/'requirements-integrations.txt')]
    if sys.version_info < (3,11):
        raise SyncError('Integration support requires Python 3.11 or newer. Offline tracking remains available.')
    import tempfile
    with tempfile.TemporaryFile(mode='w+b') as spool:
        proc = subprocess.Popen(cmd, stdout=spool, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name!='nt')
        if worker is not None: worker.child=proc
        try:
            deadline = time.monotonic() + 300
            while proc.poll() is None:
                if stop.wait(.2) or time.monotonic() > deadline:
                    kill_tree(proc)
                    raise SyncError('Support installation cancelled/timed out. No completed runtime marked. Check network and use Setup again.')
            spool.seek(0)
            import re, datetime, uuid
            tail=spool.read()[-30000:].decode('utf-8','replace')
            tail=re.sub(r'https?://[^\s]+','[package-source URL redacted]',tail)
            record='Version 0.2.0 | '+datetime.datetime.now(datetime.timezone.utc).isoformat()+' | Run '+uuid.uuid4().hex+' | Setup exit '+str(proc.returncode)+'\n'+tail
            atomic_write(Path(root)/'integration-setup.log',record.encode())
            if proc.returncode:
                raise SyncError('Integration dependency installation failed. Review integration-setup.log in the app data folder. Check internet/proxy, disk space and Python venv/pip support, then retry Setup. Offline records are retained.')
        finally:
            if worker is not None: worker.child=None
    atomic_write(v/'installed.sha256', requirements_hash().encode())
    return 'Integration support installed. Close the app and reopen using Launch-StabilityConsole.bat.'


def kill_tree(proc):
    if proc.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=8, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:
        try: os.killpg(proc.pid, 15)
        except ProcessLookupError: pass


def browser_enrich(application, message, channel, stop, progress, worker):
    if stop.is_set(): raise SyncError('Browser lookup cancelled before launch.')
    progress('Opening '+('Edge' if channel=='msedge' else 'Chrome')+' to inspect public advert evidence…')
    proc = subprocess.Popen([sys.executable, str(HERE/'browser_lookup.py')], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0), start_new_session=os.name!='nt')
    worker.child = proc
    try:
        payload = json.dumps({'application': application, 'message': message, 'browser':channel})
        proc.stdin.write(payload); proc.stdin.close(); proc.stdin=None
        deadline=time.monotonic()+150
        while True:
            if stop.is_set() or time.monotonic()>deadline:
                kill_tree(proc); raise SyncError('Browser lookup cancelled or timed out. Nothing filled; try Lookup again.')
            try:
                out, _ = proc.communicate(timeout=.2); break
            except subprocess.TimeoutExpired: continue
        if proc.returncode or len(out)>200000:
            raise SyncError('Browser lookup failed or exceeded output limits. Nothing filled.')
        return json.loads(out)
    finally:
        if proc.poll() is None: kill_tree(proc)
        worker.child=None


class InstanceLock:
    def __init__(self, root):
        self.path=Path(root)/'running.lock';self.file=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b');self.file.seek(0)
        if self.file.read(1)==b'':self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise SyncError('StabilityConsole is already running for this data folder. Switch to the existing window to avoid conflicting syncs.') from None
    def release(self):
        if self.file:self.file.close();self.file=None
