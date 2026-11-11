"""Gmail controls and evidence review, kept on Tk's main thread."""
import json
import os
import sqlite3
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import queue
import webbrowser
from urllib.parse import urlencode
from core import connect, applications, update_application, log, backup
from mail_sync import (AppWorker, SyncError, DEFAULTS, credentials, GmailClient, import_client,
                       init_mail, read_settings, save_settings, sync_mail, stamp, normal)
from integration_runtime import runtime_ready, install_runtime, browser_enrich, kill_tree

BG='#150e0e'; PANEL='#241716'; FIELD='#352221'; GOLD='#d6a36a'; FG='#f5e9e3'; MUTED='#b7a5a0'


def apply_lookup(conn, account, message_id, app_id, result, manual=False):
    init_mail(conn)
    proposal = result.get('proposal', {})
    values = proposal.get('values', {})
    applied = []
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = conn.execute('SELECT * FROM applications WHERE id=?', (app_id,)).fetchone()
        if current is None: raise ValueError('Application no longer exists.')
        consistent = normal(current['title']) == normal(proposal.get('details', {}).get('title', ''))
        if current['employer'] and normal(current['employer']) != normal(values.get('employer', '')): consistent=False
        if current['area'] and values.get('area') and normal(current['area']) not in normal(values['area']): consistent=False
        if proposal and ((result.get('state')=='CORROBORATED' and proposal.get('auto_eligible') and consistent) or manual):
            changes = {k:str(values[k]) for k in ('employer','area','url') if values.get(k) and not current[k].strip()}
            if changes:
                # Read and check existing values inside the same write transaction.
                changes['updated_at']=stamp()
                conn.execute('UPDATE applications SET '+', '.join(k+'=?' for k in changes)+' WHERE id=?', (*changes.values(),app_id))
                applied=[k for k in changes if k!='updated_at']
                log(conn,'application',app_id,'email-enrichment','Filled blanks: '+', '.join(applied)+'; source: '+proposal.get('source','UNKNOWN'))
        result['filled_fields']=applied
        if not consistent and not manual and result.get('state')=='CORROBORATED':
            result['state']='REVIEW';result['message']='Entered details changed or conflict with the source. Nothing overwritten.'
        conn.execute('UPDATE mail_matches SET proposal_json=?,lookup_state=? WHERE account=? AND message_id=? AND application_id=?',
                     (json.dumps(result),result.get('state','UNKNOWN'),account,message_id,app_id))
        conn.commit()
    except Exception:
        conn.rollback();raise
    return applied


class GmailPanel:
    def build_gmail(self):
        # Schema additions only; original application/task rows are preserved.
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='mail_messages'").fetchone():
            destination=self.root_dir/'before-gmail-v0.2.0.db'
            if destination.exists():destination=self.root_dir/('before-gmail-v0.2.0-'+stamp().replace(':','-')+'.db')
            backup(self.conn,destination)
        init_mail(self.conn)
        with self.conn:self.conn.execute("UPDATE mail_runs SET outcome='INTERRUPTED',finished_at=?,detail='Prior app session ended before completion; no success claimed' WHERE outcome='RUNNING'",(stamp(),))
        self.mail_worker=AppWorker();self.mail_worker.child=None
        self.mail_closed=False;self.mail_timer=None;self.mail_enabled=False
        try:self.mail_settings=read_settings(self.root_dir)
        except SyncError as e:self.mail_settings=DEFAULTS.copy();messagebox.showerror('Gmail settings',str(e))
        self.gmail=ttk.Frame(self.notebook);self.notebook.add(self.gmail,text='Gmail & advert evidence')
        f=self.gmail
        self.label(f,'GMAIL / SEMI-ACTIVE SYNC',True).pack(fill='x',padx=12,pady=(12,5))
        last=self.conn.execute('SELECT * FROM mail_runs ORDER BY rowid DESC LIMIT 1').fetchone()
        previous=(' Last recorded run: '+last['outcome']+' at '+last['finished_at']+' (historical).') if last else ''
        self.mail_status=tk.StringVar(value='UNKNOWN — Gmail has not been checked in this app session.'+previous)
        tk.Label(f,textvariable=self.mail_status,bg=PANEL,fg=GOLD,wraplength=1040,justify='left',anchor='w',padx=12,pady=10).pack(fill='x',padx=12)
        self.mail_preflight=tk.StringVar()
        tk.Label(f,textvariable=self.mail_preflight,bg=BG,fg=MUTED,wraplength=1040,justify='left',anchor='w').pack(fill='x',padx=12,pady=5)
        row=tk.Frame(f,bg=BG);row.pack(fill='x',padx=12,pady=5)
        for label,command in [('Setup support',self.mail_setup),('Import OAuth client',self.mail_import),('Connect Gmail',self.mail_connect),('Sync now',self.mail_sync_now),('Stop current run',self.mail_stop),('Disconnect',self.mail_disconnect)]:
            self.button(row,label,command).pack(side='left',padx=(0,5))
        row=tk.Frame(f,bg=BG);row.pack(fill='x',padx=12,pady=5)
        self.mail_auto=tk.BooleanVar(value=bool(self.mail_settings['enabled']))
        self.mail_enrich=tk.BooleanVar(value=bool(self.mail_settings['enrich']))
        self.mail_interval=tk.StringVar(value=str(self.mail_settings['interval_minutes']))
        self.mail_days=tk.StringVar(value=str(self.mail_settings['lookback_days']))
        self.mail_browser=tk.StringVar(value=self.mail_settings['browser'])
        tk.Checkbutton(row,text='Sync while app is open',variable=self.mail_auto,bg=BG,fg=FG,selectcolor=FIELD).pack(side='left')
        self.label(row,'Every (minutes)').pack(side='left',padx=(10,4))
        tk.Spinbox(row,from_=1,to=120,textvariable=self.mail_interval,width=4,bg=FIELD,fg=FG).pack(side='left')
        self.label(row,'Initial history (days)').pack(side='left',padx=(10,4))
        tk.Spinbox(row,from_=1,to=3650,textvariable=self.mail_days,width=5,bg=FIELD,fg=FG).pack(side='left')
        self.button(row,'Save sync settings',self.mail_save).pack(side='right')
        row=tk.Frame(f,bg=BG);row.pack(fill='x',padx=12,pady=5)
        tk.Checkbutton(row,text='After sync: browser lookup + fill corroborated blank fields',variable=self.mail_enrich,bg=BG,fg=FG,selectcolor=FIELD).pack(side='left')
        ttk.Combobox(row,textvariable=self.mail_browser,values=('msedge','chrome'),state='readonly',width=9).pack(side='left',padx=8)
        tk.Label(f,text='Separate visible browser windows. Up to 3 applications/cycle, 5 advert pages/lookup. No browser download, login, submission or CAPTCHA bypass.\nTitle-only matches stay tentative. Existing fields are never overwritten automatically. Closing this app stops synchronization.',bg=BG,fg=MUTED,justify='left',font=('Segoe UI',9)).pack(fill='x',padx=12,pady=3)
        frame=tk.Frame(f,bg=BG);frame.pack(fill='both',expand=True,padx=12,pady=5)
        cols=('received','application','subject','confidence','review','lookup')
        self.mail_tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='browse',height=7)
        for key,label,width in [('received','Message date',155),('application','Application',190),('subject','Subject',245),('confidence','Match evidence',150),('review','Review',90),('lookup','Web lookup',125)]:
            self.mail_tree.heading(key,text=label);self.mail_tree.column(key,width=width,minwidth=70)
        self.mail_tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=self.mail_tree.yview);scroll.pack(side='right',fill='y');self.mail_tree.configure(yscrollcommand=scroll.set)
        self.mail_rows={};self.mail_tree.bind('<Double-1>',lambda e:self.mail_review())
        row=tk.Frame(f,bg=BG);row.pack(fill='x',padx=12,pady=(3,10))
        for label,command in [('Review selected message',self.mail_review),('Lookup selected advert',self.mail_lookup_selected),('Open public web search',self.mail_open_search),('Google setup instructions',lambda:webbrowser.open('https://developers.google.com/workspace/gmail/api/quickstart/python'))]:
            self.button(row,label,command).pack(side='left',padx=(0,6))
        self.refresh_mail();self.mail_check_preflight();self.after(200,self.mail_poll)
        if self.mail_auto.get():self.mail_schedule(1500)

    def mail_check_preflight(self):
        support='PASS' if runtime_ready(self.root_dir) else 'WARN — choose Setup support, then restart with the launcher'
        platform='PASS' if os.name=='nt' else 'FAIL — Windows is required for DPAPI authorization storage'
        client='PASS' if (self.root_dir/'gmail-client.dpapi').exists() else 'WARN — import Google OAuth Desktop app JSON'
        token='PRESENT, not live-verified' if (self.root_dir/'gmail-token.dpapi').exists() else 'NOT CONNECTED'
        self.mail_preflight.set(f'Runtime: {support} | Windows: {platform}\nOAuth client: {client} | Account: {self.mail_settings.get("account", "UNKNOWN")} | Token: {token}')

    def refresh_mail(self):
        self.mail_rows={}
        for row in self.mail_tree.get_children():self.mail_tree.delete(row)
        account=self.mail_settings.get('account','')
        rows=self.conn.execute('''SELECT m.*,x.application_id,x.evidence,x.confidence,x.suggested_status,x.review_state,x.proposal_json,x.lookup_state,a.title
          FROM mail_matches x JOIN mail_messages m ON m.account=x.account AND m.message_id=x.message_id
          JOIN applications a ON a.id=x.application_id WHERE (?='' OR m.account=?) ORDER BY m.collected_at DESC,m.message_id DESC''',(account,account))
        for i,row in enumerate(rows):
            key=str(i);self.mail_rows[key]=dict(row)
            self.mail_tree.insert('','end',iid=key,values=(row['received_at'],row['title'],row['subject'],row['confidence'],row['review_state'],row['lookup_state']))

    def mail_selected(self):
        selection=self.mail_tree.selection()
        if not selection:messagebox.showinfo('Select email','Select a matching message first.');return None
        return self.mail_rows.get(selection[0])

    def mail_start(self,work):
        if self.mail_worker.busy:messagebox.showinfo('Run in progress','One integration run is already active. Stop it or wait for completion.');return False
        if self.mail_timer:self.after_cancel(self.mail_timer);self.mail_timer=None
        self.mail_status.set('RUNNING — waiting for live evidence…')
        self.mail_worker.start(work);return True

    def mail_setup(self):
        if not messagebox.askyesno('Install integration support','Download pinned Google OAuth and Playwright libraries into the app data folder?\n\nThis needs internet, disk space and Python venv support. It does not download or replace your browser. Existing offline tracking remains available.'):return
        self.mail_start(lambda stop,progress:install_runtime(self.root_dir,stop,progress,self.mail_worker))

    def mail_import(self):
        if self.mail_worker.busy:messagebox.showinfo('Busy','Stop or finish the current run before changing authorization.');return
        path=filedialog.askopenfilename(title='Select downloaded Google Desktop OAuth client JSON',filetypes=[('Google client JSON','*.json')])
        if not path:return
        try:
            import_client(self.root_dir,path)
            self.mail_auto.set(False);self.mail_settings['enabled']=False;save_settings(self.root_dir,self.mail_settings)
            self.mail_status.set('OAuth client imported and protected for this Windows user. Choose Connect Gmail.');self.mail_check_preflight()
        except Exception as e:messagebox.showerror('Import failed',str(e) if isinstance(e,SyncError) else 'File could not be read as a valid Google Desktop OAuth client.')

    def mail_connect(self):
        def work(stop,progress):
            progress('Complete Google read-only consent in your default browser (up to 120 seconds).')
            creds=credentials(self.root_dir,True)
            if stop.is_set():raise SyncError('Connect cancelled. Disconnect locally to remove stored authorization if consent completed.')
            profile=GmailClient(creds).get('profile')
            settings=read_settings(self.root_dir);settings['account']=profile['emailAddress'];save_settings(self.root_dir,settings)
            return 'CONNECTED — read-only Gmail account confirmed. Enable sync and save settings to start continuous checks.'
        self.mail_start(work)

    def mail_save(self):
        if self.mail_worker.busy:messagebox.showinfo('Busy','Finish or stop the current run before changing sync settings.');return
        try:
            value={**self.mail_settings,'enabled':self.mail_auto.get(),'enrich':self.mail_enrich.get(),'interval_minutes':int(self.mail_interval.get()),'lookback_days':int(self.mail_days.get()),'browser':self.mail_browser.get()}
            save_settings(self.root_dir,value);self.mail_settings=read_settings(self.root_dir)
            if self.mail_timer:self.after_cancel(self.mail_timer);self.mail_timer=None
            if value['enabled']:self.mail_schedule(100)
            self.mail_status.set('Settings saved. '+('Sync starts while this window is open.' if value['enabled'] else 'Automatic sync is paused; Sync now remains available.'))
        except (ValueError,SyncError) as e:messagebox.showerror('Settings failed',str(e))

    def mail_schedule(self,delay=None):
        if self.mail_closed or not self.mail_auto.get():return
        if self.mail_timer:self.after_cancel(self.mail_timer)
        self.mail_timer=self.after(delay if delay is not None else self.mail_settings['interval_minutes']*60000,self.mail_auto_tick)

    def mail_auto_tick(self):
        self.mail_timer=None
        if not self.mail_closed and self.mail_auto.get():
            if self.mail_worker.busy:self.mail_schedule(1000)
            else:self.mail_sync_now()

    def mail_sync_now(self):
        settings=self.mail_settings.copy()
        def work(stop,progress):
            conn=connect(self.root_dir/'stability.db')
            try:
                creds=credentials(self.root_dir)
                summary=sync_mail(conn,GmailClient(creds),settings,stop,progress)
                inspected=0;issues=0
                if settings['enrich']:
                    account=settings.get('account','')
                    pending=conn.execute('''SELECT m.*,x.application_id FROM mail_matches x JOIN mail_messages m ON m.account=x.account AND m.message_id=x.message_id
                        WHERE x.lookup_state='Not requested' AND x.review_state<>'Ignored' AND m.account=? ORDER BY m.collected_at DESC''',(account,)).fetchall()
                    seen=set()
                    for row in pending:
                        if stop.is_set():raise SyncError('Sync cancelled after mail collection; existing evidence remains.')
                        if row['application_id'] in seen:continue
                        if inspected>=3:break
                        seen.add(row['application_id']);inspected+=1
                        app=dict(conn.execute('SELECT * FROM applications WHERE id=?',(row['application_id'],)).fetchone())
                        msg=dict(row);msg['links']=json.loads(msg['links_json'])
                        try:result=browser_enrich(app,msg,settings['browser'],stop,progress,self.mail_worker)
                        except SyncError as e:result={'state':'FAILED','message':str(e)}
                        apply_lookup(conn,msg['account'],msg['message_id'],app['id'],result)
                        if result['state']!='CORROBORATED':issues+=1
                return 'MAIL COLLECTION — '+summary+f' | Browser lookups: {inspected}; review/failed: {issues}. Remaining pending applications continue next cycle.'
            finally:conn.close()
        self.mail_start(work)

    def mail_stop(self):
        self.mail_worker.cancel();self.mail_status.set('Stop requested. Current HTTP request may take up to 20 seconds; Google consent up to 120 seconds. Automatic scheduling is paused until settings are saved again.')
        self.mail_auto.set(False);self.mail_settings['enabled']=False;save_settings(self.root_dir,self.mail_settings)
        if self.mail_timer:self.after_cancel(self.mail_timer);self.mail_timer=None

    def mail_disconnect(self):
        if self.mail_worker.busy:messagebox.showinfo('Busy','Stop/finish the current run before disconnecting.');return
        self.mail_auto.set(False);self.mail_settings['enabled']=False;save_settings(self.root_dir,self.mail_settings)
        (self.root_dir/'gmail-token.dpapi').unlink(missing_ok=True)
        if self.mail_timer:self.after_cancel(self.mail_timer);self.mail_timer=None
        self.mail_status.set('DISCONNECTED locally. Saved email evidence remains historical. To revoke Google consent too, remove the app in your Google account permissions.');self.mail_check_preflight()

    def mail_poll(self):
        if self.mail_closed:return
        try:
            while True:
                kind,value=self.mail_worker.events.get_nowait()
                self.mail_status.set(('FAILED — ' if kind=='error' else '')+str(value))
                if kind in ('done','error'):
                    try:self.mail_settings=read_settings(self.root_dir)
                    except SyncError:pass
                    self.refresh_mail();self.refresh_all();self.mail_check_preflight();self.mail_schedule()
        except queue.Empty:pass
        self.after(200,self.mail_poll)

    def mail_open_search(self):
        row=self.mail_selected()
        if not row:return
        app=self.conn.execute('SELECT * FROM applications WHERE id=?',(row['application_id'],)).fetchone()
        query=' '.join(x for x in ('"'+app['title']+'"',app['employer'],app['area'],'job vacancy') if x)
        webbrowser.open('https://www.google.com/search?'+urlencode({'q':query}))

    def mail_lookup_selected(self):
        row=self.mail_selected()
        if not row:return
        app=dict(self.conn.execute('SELECT * FROM applications WHERE id=?',(row['application_id'],)).fetchone())
        msg=dict(row);msg['links']=json.loads(msg['links_json']);channel=self.mail_browser.get()
        def work(stop,progress):
            result=browser_enrich(app,msg,channel,stop,progress,self.mail_worker)
            conn=connect(self.root_dir/'stability.db')
            try:filled=apply_lookup(conn,msg['account'],msg['message_id'],app['id'],result)
            finally:conn.close()
            return 'LOOKUP '+result['state']+' — '+result.get('message','')+' | Filled: '+(', '.join(filled) or 'none')
        self.mail_start(work)

    def mail_review(self):
        row=self.mail_selected()
        if not row:return
        d=tk.Toplevel(self);d.title('Gmail evidence — review before changing status');d.geometry('880x720');d.configure(bg=BG);d.transient(self)
        text=tk.Text(d,bg=PANEL,fg=FG,wrap='word',font=('Segoe UI',10));text.pack(fill='both',expand=True,padx=12,pady=12)
        result=json.loads(row['proposal_json']);proposal=result.get('proposal',{})
        lookup_lines=['Result: '+row['lookup_state'],result.get('message','No browser lookup recorded.'),
                      'Fields filled: '+(', '.join(result.get('filled_fields',[])) or 'none')]
        for i,candidate in enumerate(result.get('candidates',[]),1):
            lookup_lines += ['', 'Advert candidate '+str(i), 'Source: '+candidate.get('source','UNKNOWN'),
                             'Checked: '+candidate.get('checked_at','UNKNOWN'), 'Match evidence: '+candidate.get('evidence','UNKNOWN')]
            lookup_lines += [key.replace('_',' ').title()+': '+str(value) for key,value in candidate.get('details',{}).items()]
        lookup_lines += ['Source check issue: '+str(x) for x in result.get('failures',[])]
        info=f"ACCOUNT: {row['account']}\nFROM: {row['sender']}\nSUBJECT: {row['subject']}\nDATE: {row['received_at']}\nMESSAGE ID: {row['message_id']}\nTHREAD: {row['thread_id']}\n\nMATCH: {row['confidence']}\n{row['evidence']}\n\nSUGGESTED STATUS (not applied): {row['suggested_status'] or 'UNKNOWN'}\n\n{row['body']}\n\nWEB LOOKUP EVIDENCE:\n"+'\n'.join(lookup_lines)

        text.insert('1.0',info);text.configure(state='disabled')
        rowbar=tk.Frame(d,bg=BG);rowbar.pack(fill='x',padx=12,pady=6)
        def link():
            with self.conn:
                self.conn.execute('INSERT OR IGNORE INTO mail_bindings VALUES (?,?,?)',(row['account'],row['thread_id'],row['application_id']))
                self.conn.execute("UPDATE mail_matches SET review_state='Linked',confidence='Confirmed thread' WHERE account=? AND message_id=? AND application_id=?",(row['account'],row['message_id'],row['application_id']))
            self.refresh_mail();messagebox.showinfo('Linked','This email thread is linked to the selected application. Status has not changed.',parent=d)
        def status():
            target=row['suggested_status']
            if not target:messagebox.showinfo('Unknown','No status suggestion exists. Edit the application after reading the email.',parent=d);return
            if messagebox.askyesno('Confirm status',f"Set application #{row['application_id']} to {target}?\n\nRead the message first; quoted history and generic wording can make suggestions wrong.",parent=d):
                update_application(self.conn,row['application_id'],status=target);link();self.refresh_all()
        def fill():
            if not proposal:messagebox.showinfo('No proposal','Run Lookup selected advert first. Ambiguous or failed lookups do not have an automatic proposal.',parent=d);return
            if messagebox.askyesno('Review source proposal','Fill only currently empty employer, location and URL fields using this displayed source? Existing values are preserved.',parent=d):
                filled=apply_lookup(self.conn,row['account'],row['message_id'],row['application_id'],result,True);self.refresh_all();self.refresh_mail();messagebox.showinfo('Fields updated',', '.join(filled) or 'No blank fields to fill.',parent=d)
        for label,command in [('Link this thread',link),('Accept suggested status',status),('Accept blank-field proposal',fill)]:self.button(rowbar,label,command).pack(side='left',padx=(0,6))
        rowbar=tk.Frame(d,bg=BG);rowbar.pack(fill='x',padx=12,pady=(0,12))
        def ignore():
            with self.conn:self.conn.execute("UPDATE mail_matches SET review_state='Ignored' WHERE account=? AND message_id=? AND application_id=?",(row['account'],row['message_id'],row['application_id']))
            self.refresh_mail();d.destroy()
        self.button(rowbar,'Ignore this match',ignore).pack(side='left')
        self.button(rowbar,'Open in Gmail',lambda:webbrowser.open('https://mail.google.com/mail/?'+urlencode({'authuser':row['account']})+'#all/'+row['message_id'])).pack(side='left',padx=6)
        if proposal.get('source'):self.button(rowbar,'Open advert source',lambda:webbrowser.open(proposal['source'])).pack(side='left')
        self.button(rowbar,'Close',d.destroy).pack(side='right')

    def gmail_close(self):
        self.mail_closed=True
        if self.mail_timer:self.after_cancel(self.mail_timer)
        self.mail_worker.close()
        child=getattr(self.mail_worker,'child',None)
        if child and child.poll() is None:
            # Only the integration subprocess launched by this app is targeted.
            if os.name=='nt':
                subprocess.Popen(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:
                try:kill_tree(child)
                except Exception:pass
