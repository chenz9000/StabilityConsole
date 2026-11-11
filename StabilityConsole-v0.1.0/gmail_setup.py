"""Resumable in-app setup: prepare libraries, guide Google registration, sign in."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox
import webbrowser
from mail_sync import SCOPE, SyncError, atomic_write, stamp
from integration_runtime import runtime_ready, runtime_paths, InstanceLock

BG='#150e0e'; PANEL='#241716'; FG='#f5e9e3'; GOLD='#d6a36a'; MUTED='#b7a5a0'
CHECKPOINT='gmail-setup-progress.json'
GOOGLE_STEPS=(
    ('Choose your Google project',
     'Open Google below. Use the account whose Gmail you want to connect. Select a project you control, or create one named StabilityConsole. Keep using that same project for the following steps.',
     'https://console.cloud.google.com/apis/enableflow;apiid=gmail.googleapis.com',None),
    ('Allow this project to read Gmail',
     'On the Gmail API page, choose Enable. If it already shows that Gmail is enabled, continue. This enables the connection; it does not give the app access to your inbox yet.',
     'https://console.cloud.google.com/apis/enableflow;apiid=gmail.googleapis.com',None),
    ('Give the connection a name',
     'In Google Auth, start the app configuration if asked. Name it StabilityConsole and use your own email for the contact details. For a personal Gmail account, choose External when Google asks who can use it. Review any Google terms yourself.',
     'https://console.developers.google.com/auth/branding','StabilityConsole'),
    ('Allow your own Gmail account',
     'Under Audience, keep this personal connection in Testing and add your own Gmail address to the test-user list. If Google says Internal, change the audience to External for a personal Gmail address.',
     'https://console.developers.google.com/auth/audience',None),
    ('Choose read-only email access',
     'Under Data Access, add the Gmail read-only permission shown below. You can copy its value with the button. This app does not need permission to send, delete or change your mail.',
     'https://console.developers.google.com/auth/scopes',SCOPE),
    ('Download the Google connection file',
     'Under Clients, create a client with application type Desktop app. Name it StabilityConsole, then download its JSON file. Return here and choose that downloaded file. The app will validate and protect it locally.',
     'https://console.developers.google.com/auth/clients',None),
)


def checkpoint(root):
    path=Path(root)/CHECKPOINT
    if not path.exists():return {'active':False,'google_step':0}
    try:
        value=json.loads(path.read_text('utf-8'))
        return {'active':value.get('active') is True,
                'google_step':max(0,min(len(GOOGLE_STEPS)-1,int(value.get('google_step',0))))}
    except (OSError,ValueError,TypeError):
        return {'active':False,'google_step':0,'warning':'Setup progress could not be read. Your application and Gmail evidence records are unchanged.'}


def save_checkpoint(root,active=True,google_step=0):
    if not 0<=int(google_step)<len(GOOGLE_STEPS):raise ValueError('Invalid Google setup step.')
    atomic_write(Path(root)/CHECKPOINT,json.dumps({'active':bool(active),'google_step':int(google_step),'updated_at':stamp(),'version':'0.2.1'}).encode())


def active_runtime(root):
    _,python=runtime_paths(root)
    return os.path.normcase(os.path.abspath(sys.executable))==os.path.normcase(os.path.abspath(str(python)))


def setup_phase(root,verified=False,ready=None,active=None,platform=None):
    """File presence is a setup prerequisite, never proof of Google authorization."""
    root=Path(root)
    if (os.name if platform is None else platform)!='nt':return 'unsupported'
    if not (runtime_ready(root) if ready is None else ready):return 'support'
    if not (active_runtime(root) if active is None else active):return 'restart'
    if not (root/'gmail-client.dpapi').exists():return 'registration'
    if verified:return 'ready'
    return 'verify' if (root/'gmail-token.dpapi').exists() else 'signin'


def wait_for_restart_unlock(root,timeout=20):
    deadline=time.monotonic()+timeout
    while True:
        lock=InstanceLock(root)
        try:
            lock.acquire();lock.release();return
        except SyncError:
            if time.monotonic()>=deadline:
                raise SyncError('The previous app window did not finish closing. Open the normal launcher again; Gmail setup will resume.') from None
            time.sleep(.1)


def restart_command():
    return [sys.executable,str(Path(__file__).with_name('launch.py')),'--resume-gmail-setup','--wait-for-lock']


class GmailSetup(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app)
        self.app=app;self.closed=False;self.action=None;self.restarting=False
        self.title('Set up Gmail — StabilityConsole');self.geometry('780x620');self.minsize(660,560)
        self.configure(bg=BG);self.transient(app);self.protocol('WM_DELETE_WINDOW',self.dismiss)
        state=checkpoint(app.root_dir);self.google_step=state['google_step'];save_checkpoint(app.root_dir,True,self.google_step)
        tk.Label(self,text='SET UP GMAIL',font=('Segoe UI',19,'bold'),bg=BG,fg=GOLD).pack(anchor='w',padx=24,pady=(20,5))
        self.title_text=tk.StringVar();self.body_text=tk.StringVar();self.evidence_text=tk.StringVar()
        tk.Label(self,textvariable=self.title_text,font=('Segoe UI',14,'bold'),bg=BG,fg=FG,anchor='w').pack(fill='x',padx=24,pady=(8,12))
        body_frame=tk.Frame(self,bg=PANEL);body_frame.pack(fill='both',expand=True,padx=24)
        self.body_box=tk.Text(body_frame,bg=PANEL,fg=FG,font=('Segoe UI',11),wrap='word',height=12,relief='flat',padx=16,pady=16,state='disabled')
        self.body_box.pack(side='left',fill='both',expand=True)
        scrollbar=tk.Scrollbar(body_frame,command=self.body_box.yview);scrollbar.pack(side='right',fill='y')
        self.body_box.configure(yscrollcommand=scrollbar.set)
        self.last_body=None

        self.copy_text=tk.StringVar()
        self.copy_label=tk.Label(self,textvariable=self.copy_text,bg=BG,fg=GOLD,justify='left',wraplength=690,font=('Segoe UI',10))
        self.copy_label.pack(fill='x',padx=24,pady=6)
        tk.Label(self,textvariable=app.mail_status,bg=BG,fg=MUTED,wraplength=690,justify='left',font=('Segoe UI',9)).pack(fill='x',padx=24,pady=5)
        tk.Label(self,textvariable=self.evidence_text,bg=BG,fg=MUTED,wraplength=690,justify='left',font=('Segoe UI',9)).pack(fill='x',padx=24,pady=5)
        row=tk.Frame(self,bg=BG);row.pack(fill='x',padx=24,pady=(8,5))
        self.back=app.button(row,'Back',self.go_back);self.back.pack(side='left')
        self.open_button=app.button(row,'Open Google',self.open_google);self.open_button.pack(side='left',padx=8)
        self.copy_button=app.button(row,'Copy value',self.copy_value);self.copy_button.pack(side='left')
        self.primary=app.button(row,'Continue',self.proceed);self.primary.pack(side='right')
        row=tk.Frame(self,bg=BG);row.pack(fill='x',padx=24,pady=(0,18))
        self.import_button=app.button(row,'Choose downloaded Google file',self.pick_client);self.import_button.pack(side='left')
        app.button(row,'Set up later',self.dismiss).pack(side='right')
        self.refresh();self.after(250,self.tick)

    def phase(self):return setup_phase(self.app.root_dir,verified=getattr(self.app,'mail_verified',False))

    def refresh(self):
        phase=self.phase();busy=self.app.mail_worker.busy
        self.open_button.configure(state='disabled',text='Open Google',command=self.open_google);self.copy_button.configure(state='disabled');self.back.configure(state='disabled')
        self.import_button.configure(state='disabled');self.primary.configure(state='disabled' if busy else 'normal')
        self.copy_text.set('')
        if phase=='unsupported':
            self.title_text.set('Windows is needed for Gmail setup')
            self.body_text.set('Gmail authorization is protected using your Windows account. This setup cannot complete on this operating system. Your offline tracker is still available. Open this app on your Windows laptop to connect Gmail.')
            self.primary.configure(text='Close setup')
        elif phase=='support':
            self.title_text.set('1 · Let the app prepare Gmail support')
            self.body_text.set('Click Install support. StabilityConsole will download the required libraries into its own local folder, then reopen itself and continue this wizard.\n\nExpect roughly 50–70 MB of downloads and a few minutes. Your records stay in place. Your installed Edge or Chrome will be reused; no browser is replaced.\n\nNo terminal commands or manual package installation are needed.')
            self.primary.configure(text='Installing…' if busy else 'Install support')
        elif phase=='restart':
            self.title_text.set('1 · Support is installed')
            self.body_text.set('The app needs to reopen once to load the new libraries. It will save your place and return to this wizard automatically. Your application records will stay in the same folder.')
            self.primary.configure(text='Reopen and continue')
        elif phase=='registration':
            title,body,url,value=GOOGLE_STEPS[self.google_step]
            self.title_text.set(f'2 · Google setup {self.google_step+1}/{len(GOOGLE_STEPS)} — '+title)
            self.body_text.set('This copy of StabilityConsole has no shared Google sign-in registration. Google requires a one-time registration before this app can offer normal Gmail sign-in.\n\n'+body+'\n\nThe browser step is guided here, but it is completed by you on Google. Clicking Continue records your place; it does not prove that Google accepted the configuration.')
            self.open_button.configure(state='disabled' if busy else 'normal')
            self.back.configure(state='normal' if self.google_step>0 and not busy else 'disabled')
            self.import_button.configure(state='disabled' if busy else 'normal')
            if value:self.copy_text.set(value);self.copy_button.configure(state='normal')
            self.primary.configure(text='Choose downloaded file' if self.google_step==len(GOOGLE_STEPS)-1 else 'I finished this step')
        elif phase in ('signin','verify'):
            self.title_text.set('3 · '+('Check your existing Gmail connection' if phase=='verify' else 'Sign in through Google'))
            self.body_text.set('Your Google connection file has been imported.\n\n'+('The app will check the saved authorization against Gmail. If it expired, the wizard will offer sign-in again.' if phase=='verify' else 'Click Sign in to Gmail. Google will open in your normal browser. Choose your Gmail account and approve read-only email access, then return here.')+'\n\nYou do not enter your Google password in StabilityConsole. The app will confirm which mailbox was connected before it starts syncing.')
            self.primary.configure(text='Checking…' if busy else 'Check connection' if phase=='verify' else 'Sign in to Gmail')
            self.open_button.configure(text='Google connection settings',state='disabled' if busy else 'normal',command=lambda:webbrowser.open(GOOGLE_STEPS[1][2]))
            self.import_button.configure(state='disabled' if busy else 'normal')
        else:
            self.title_text.set('4 · Gmail connection checked')
            account=self.app.mail_settings.get('account','UNKNOWN')
            self.body_text.set('Gmail confirmed the connected account:\n\n'+account+'\n\nClick Start syncing to begin automatic checks while this app is open. The interval is shown in the Gmail tab and can be changed there. Closing the app stops checks.\n\nAfter sync, the selected browser can research matching adverts and fill corroborated blank fields. Existing values and uncertain matches remain for review.')
            self.primary.configure(text='Start syncing')
        if self.last_body!=self.body_text.get():
            self.body_box.configure(state='normal');self.body_box.delete('1.0','end');self.body_box.insert('1.0',self.body_text.get());self.body_box.configure(state='disabled');self.body_box.yview_moveto(0)
            self.last_body=self.body_text.get()
        self.evidence_text.set('Setup saved locally · Google configuration is verified only by a successful Gmail connection check.\n'+('Setup is running. Progress appears above; automatic mail checks are paused while this wizard is open.' if busy else 'You can close this wizard and return using Set up Gmail.'))

    def tick(self):
        if self.closed or not self.winfo_exists():return
        if self.action=='install' and not self.app.mail_worker.busy:
            self.action=None
            if runtime_ready(self.app.root_dir):self.restart();return
        if self.action=='verify' and not self.app.mail_worker.busy and not getattr(self.app,'mail_verified',False):
            self.action=None
            # A failed saved-token check is not a successful connection and should allow a fresh sign-in.
            problem=self.app.mail_status.get().casefold()
            self.force_signin=any(word in problem for word in ('expired','revoked','401','not connected','another gmail','scope'))
        self.refresh()
        if getattr(self,'force_signin',False) and self.phase()=='verify' and not self.app.mail_worker.busy:
            self.primary.configure(text='Sign in again')
        self.after(250,self.tick)

    def proceed(self):
        if self.app.mail_worker.busy:return
        phase=self.phase()
        if phase=='unsupported':self.dismiss()
        elif phase=='support':
            self.action='install';self.app.mail_setup(confirm=False)
        elif phase=='restart':self.restart()
        elif phase=='registration':
            if self.google_step==len(GOOGLE_STEPS)-1:self.pick_client()
            else:self.google_step+=1;save_checkpoint(self.app.root_dir,True,self.google_step);self.refresh()
        elif phase in ('signin','verify'):
            self.action='verify'
            self.app.mail_connect(interactive=phase=='signin' or getattr(self,'force_signin',False))
            self.force_signin=False
        elif phase=='ready':
            self.closed=True
            self.app.mail_auto.set(True)
            if not self.app.mail_save():
                self.closed=False;return
            save_checkpoint(self.app.root_dir,False,self.google_step)
            self.closed=True;self.destroy();self.app.notebook.select(self.app.gmail)

    def open_google(self):
        url=GOOGLE_STEPS[self.google_step][2]
        if not webbrowser.open(url):messagebox.showerror('Browser did not open','Open the Google setup page using your default browser, then return here.',parent=self)

    def copy_value(self):
        value=GOOGLE_STEPS[self.google_step][3]
        if value:self.clipboard_clear();self.clipboard_append(value)

    def pick_client(self):
        if self.app.mail_worker.busy:return
        self.app.mail_import()
        self.force_signin=False;self.refresh()

    def go_back(self):
        if self.app.mail_worker.busy:return
        self.google_step=max(0,self.google_step-1);save_checkpoint(self.app.root_dir,True,self.google_step);self.refresh()

    def restart(self):
        if self.restarting:return
        save_checkpoint(self.app.root_dir,True,self.google_step)
        self.restarting=True
        try:
            logfile=(self.app.root_dir/'setup-restart.log').open('ab')
            try:subprocess.Popen(restart_command(),stdout=logfile,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
            finally:logfile.close()
        except OSError:
            self.restarting=False;messagebox.showerror('Could not reopen automatically','Your place is saved. Open Launch-StabilityConsole.bat again; this wizard will resume.',parent=self);return
        self.closed=True;self.app.close()

    def dismiss(self):
        if self.closed:return
        if self.app.mail_worker.busy:self.app.mail_stop()
        save_checkpoint(self.app.root_dir,False,self.google_step)
        self.closed=True;self.destroy()
        if not self.app.mail_closed:self.app.mail_schedule()
