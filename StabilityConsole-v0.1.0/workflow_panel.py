"""Private workflow UI. Network checks reuse the existing read-only Gmail worker."""
import json
import hashlib
import os
import queue
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import tkinter as tk

from core import connect
from mail_sync import AppWorker
from job_workflow import (ensure_schema, recover_sessions, load_report, import_report,
    report_summary, save_fact, FACT_STATES, link_document, approve_document, file_digest,
    start_session, complete_session, retry_check, due_check, check_result, parse_time)

from theme import BG, PANEL, FIELD, ACCENT, FG, MUTED, stripe_rows, wrap_labels


class WorkflowPanel:
    def build_workflow(self):
        ensure_schema(self.conn, self.root_dir)
        recover_sessions(self.conn)
        self.workflow_closed=False
        self.workflow_io=AppWorker()
        self.workflow_callback=None
        self.workflow_after=None
        self.workflow=ttk.Frame(self.notebook)
        self.notebook.add(self.workflow,text='Job-search workflow')
        self.label(self.workflow,'Job-search workflow',True).pack(fill='x',padx=12,pady=(12,5))
        self.workflow_status=tk.StringVar(value='Local records. Importing reports does not send applications or verify Gmail live.')
        tk.Label(self.workflow,textvariable=self.workflow_status,bg=PANEL,fg=ACCENT,anchor='w',justify='left',wraplength=1000,padx=10,pady=8).pack(fill='x',padx=12)
        row=tk.Frame(self.workflow,bg=BG);row.pack(fill='x',padx=12,pady=7)
        self.button(row,'Import session report',self.workflow_import,primary=True).pack(side='left')
        self.button(row,'Start session',self.workflow_start).pack(side='left',padx=5)
        self.button(row,'Complete session',self.workflow_complete).pack(side='left')
        row=tk.Frame(self.workflow,bg=BG);row.pack(fill='x',padx=12,pady=(0,5))
        self.button(row,'Retry due mail check',self.workflow_retry).pack(side='left',padx=5)
        self.button(row,'Cancel file operation',self.workflow_cancel).pack(side='left')
        tk.Label(self.workflow,text='Target: about 15 minutes of useful work. Completing a session schedules a read-only Gmail check five minutes later.\nChecks run while this app is open. Overdue waiting checks resume on reopening; interrupted checks require retry. No mail is sent.',bg=BG,fg=MUTED,justify='left',wraplength=1020).pack(fill='x',padx=12,pady=(0,5))
        tabs=ttk.Notebook(self.workflow);tabs.pack(fill='both',expand=True,padx=12,pady=5)
        self.workflow_sessions=self.workflow_table(tabs,'Sessions',('title','state','started','due','check'),('Session','State','Started','Mail check due','Check outcome'),(180,100,170,170,115))
        self.workflow_apps=self.workflow_table(tabs,'Application evidence',('id','title','employer','reported','state'),('Report ID','Position','Employer','Reported status','Current status'),(150,220,160,130,130))
        self.workflow_apps.bind('<Double-1>',lambda _:self.workflow_show_evidence())
        facts=ttk.Frame(tabs);tabs.add(facts,text='Confirmed profile')
        self.workflow_facts=self.workflow_table(facts,None,('name','value','state'),('Field','Value','Confirmation'),(200,500,150))
        self.workflow_facts.bind('<Double-1>',lambda _:self.workflow_edit_fact())
        row=tk.Frame(facts,bg=BG);row.pack(fill='x',pady=5)
        self.button(row,'Add / edit selected field',self.workflow_edit_fact).pack(side='left')
        docs=ttk.Frame(tabs);tabs.add(docs,text='Documents and approval')
        self.workflow_docs=self.workflow_table(docs,None,('name','state','hash'),('Document revision','Recorded review / send state','SHA-256 prefix'),(380,260,150))
        row=tk.Frame(docs,bg=BG);row.pack(fill='x',pady=5)
        self.button(row,'Link local file revision',self.workflow_link_document).pack(side='left')
        self.button(row,'Approve reviewed file',self.workflow_approve).pack(side='left',padx=5)
        self.button(row,'Show document evidence',self.workflow_show_document).pack(side='left')
        self.button(row,'Open local file',self.workflow_open_document).pack(side='left',padx=5)
        tk.Label(docs,text='Approval belongs to an exact file hash. Changed files need a new revision and review. Imported states are source-report evidence, not live file verification.',bg=BG,fg=MUTED,wraplength=1000,justify='left').pack(fill='x',pady=5)
        self.workflow_details=tk.Text(self.workflow,height=4,bg=PANEL,fg=FG,wrap='word',font=('Segoe UI',9))
        self.workflow_details.pack(fill='x',padx=12,pady=(0,8));self.workflow_details.configure(state='disabled')
        self.workflow_sessions.bind('<<TreeviewSelect>>',lambda _:self.workflow_session_detail())
        self.workflow_refresh()
        self.workflow_after=self.after(200,self.workflow_tick)

    def workflow_table(self,parent,name,columns,labels,widths):
        page=ttk.Frame(parent)
        if name:parent.add(page,text=name)
        else:page.pack(fill='both',expand=True)
        tree=ttk.Treeview(page,columns=columns,show='headings',height=6,selectmode='browse')
        for col,label,width in zip(columns,labels,widths):
            tree.heading(col,text=label);tree.column(col,width=width,minwidth=70)
        tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(page,orient='vertical',command=tree.yview);scroll.pack(side='right',fill='y')
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def workflow_fill(self,tree,items):
        selected=tree.selection()
        tree.delete(*tree.get_children())
        for ident,values in items:tree.insert('','end',iid=str(ident),values=values)
        stripe_rows(tree)
        if selected and tree.exists(selected[0]):tree.selection_set(selected[0])

    def workflow_refresh(self):
        if not hasattr(self,'workflow_sessions'):return
        def local_time(value):
            return parse_time(value).astimezone().strftime('%d %b %H:%M:%S') if value else ''
        sessions=self.conn.execute('SELECT * FROM workflow_sessions ORDER BY started_at DESC').fetchall()
        self.workflow_fill(self.workflow_sessions,[(r['id'],(r['title'],r['state'],local_time(r['started_at']),local_time(r['check_due']),r['check_state'])) for r in sessions])
        rows=self.conn.execute('SELECT l.source_id,l.baseline_json,a.* FROM workflow_links l JOIN applications a ON a.id=l.application_id ORDER BY a.updated_at DESC').fetchall()
        self.workflow_fill(self.workflow_apps,[(r['source_id'],(r['source_id'].split(':')[-1],r['title'],r['employer'],json.loads(r['baseline_json']).get('status','Unknown'),r['status'])) for r in rows])
        facts=self.conn.execute('SELECT * FROM workflow_facts ORDER BY name').fetchall()
        self.workflow_fill(self.workflow_facts,[(r['name'],(r['name'],r['value'],r['state'])) for r in facts])
        self.workflow_doc_rows={}
        docs=self.conn.execute('SELECT * FROM workflow_documents ORDER BY updated_at DESC,filename').fetchall()
        items=[]
        for r in docs:
            ident=hashlib.sha256((r['document_key']+'\0'+r['sha256']).encode()).hexdigest()
            self.workflow_doc_rows[ident]=dict(r)
            items.append((ident,(r['filename'],r['state']+' (recorded)',r['sha256'][:16])))
        self.workflow_fill(self.workflow_docs,items)

    def workflow_note(self,text):
        self.workflow_details.configure(state='normal');self.workflow_details.delete('1.0','end')
        self.workflow_details.insert('1.0',text);self.workflow_details.configure(state='disabled')

    def workflow_session_detail(self):
        selected=self.workflow_sessions.selection()
        if selected:
            row=self.conn.execute('SELECT * FROM workflow_sessions WHERE id=?',(selected[0],)).fetchone()
            if row:self.workflow_note(f"{row['check_state']}: {row['check_detail']}\nGmail run: {row['mail_run_id'] or 'not recorded'}")

    def workflow_io_start(self,work,callback):
        if self.workflow_io.busy:
            messagebox.showinfo('Operation in progress','Wait for the current import/file operation to finish.');return
        self.workflow_callback=callback
        self.workflow_status.set('RUNNING — reading local evidence…')
        self.workflow_io.start(work)

    def workflow_import(self):
        path=filedialog.askopenfilename(title='Import private Income Command session report',filetypes=[('Workflow JSON report','*.json')])
        if not path:return
        def preview(value):
            report,digest=value
            detail=f"Account: {report['account']}\nReport: {report['report_id']}\n{report_summary(report)}\nProfile fields: {len(report.get('profile',[]))}; document revisions: {len(report.get('documents',[]))}\n\nImport these externally recorded actions? Existing local edits are preserved; no application is sent and Gmail is not checked by importing."
            if not messagebox.askyesno('Review session report',detail):
                self.workflow_status.set('Import cancelled. Existing records unchanged.');return
            def work(stop,progress):
                # Re-read to detect replacement between preview and confirmation.
                current,current_digest=load_report(path,stop)
                if current_digest!=digest:raise ValueError('Report changed after preview. Choose it again and review the new contents.')
                conn=connect(self.root_dir/'stability.db')
                try:return import_report(conn,current,current_digest,path,stop,progress)
                finally:conn.close()
            def done(result):
                self.workflow_status.set('IMPORT RECORDED — '+('Already imported; nothing duplicated.' if result['duplicate'] else f"{result['created']} new; {result['updated']} updated; {result['preserved']} local field(s) preserved."))
                self.refresh_all();self.workflow_refresh()
            self.workflow_io_start(work,done)
        self.workflow_io_start(lambda stop,progress:load_report(path,stop),preview)

    def workflow_cancel(self):
        self.workflow_io.cancel()
        self.workflow_status.set('Cancellation requested. An in-flight file read/database wait must return first; a completed import is retained.')

    def workflow_start(self):
        try:
            ident=start_session(self.conn)
            self.workflow_refresh();self.workflow_sessions.selection_set(ident)
            self.workflow_status.set('Session started. Work on useful actions; elapsed time is not proof of applications submitted.')
        except ValueError as exc:messagebox.showinfo('Session',str(exc))

    def workflow_complete(self):
        row=self.conn.execute("SELECT id FROM workflow_sessions WHERE state='ACTIVE'").fetchone()
        if not row:messagebox.showinfo('No active session','Start a session before marking it complete.');return
        complete_session(self.conn,row['id']);self.workflow_refresh()
        self.workflow_status.set('Session complete. Gmail check scheduled in five minutes; keep the app open.')

    def workflow_retry(self):
        selected=self.workflow_sessions.selection()
        if not selected:messagebox.showinfo('Select session','Select the completed session to retry.');return
        try:retry_check(self.conn,selected[0]);self.workflow_refresh()
        except ValueError as exc:messagebox.showinfo('Retry',str(exc))

    def workflow_edit_fact(self):
        selected=self.workflow_facts.selection()
        row=self.conn.execute('SELECT * FROM workflow_facts WHERE name=?',(selected[0],)).fetchone() if selected else None
        dialog=tk.Toplevel(self);dialog.title('Confirmed profile field');dialog.configure(bg=BG);dialog.transient(self);dialog.grab_set()
        controls=[]
        for i,(label,value) in enumerate([('Field',row['name'] if row else ''),('Value',row['value'] if row else '')]):
            tk.Label(dialog,text=label,bg=BG,fg=FG).grid(row=i,column=0,padx=12,pady=10)
            entry=tk.Entry(dialog,width=65,bg=FIELD,fg=FG,insertbackground=FG);entry.insert(0,value);entry.grid(row=i,column=1,padx=12,pady=10);controls.append(entry)
            if row and i==0:entry.configure(state='readonly')
        state=ttk.Combobox(dialog,values=FACT_STATES,state='readonly');state.set(row['state'] if row else 'UNKNOWN');state.grid(row=2,column=1,padx=12,pady=8,sticky='w')
        def save():
            try:save_fact(self.conn,controls[0].get(),controls[1].get(),state.get());self.workflow_refresh();dialog.destroy()
            except ValueError as exc:messagebox.showerror('Check field',str(exc),parent=dialog)
        self.button(dialog,'Save reviewed field',save).grid(row=3,column=1,pady=12,sticky='w')

    def workflow_selected_doc(self):
        selected=self.workflow_docs.selection()
        return self.workflow_doc_rows.get(selected[0]) if selected else None

    def workflow_link_document(self):
        old=self.workflow_selected_doc()
        path=filedialog.askopenfilename(title='Link a local document for review; nothing is uploaded')
        if not path:return
        key=old['document_key'] if old else 'local:'+Path(path).name
        def work(stop,progress):
            conn=connect(self.root_dir/'stability.db')
            try:return link_document(conn,key,path,old['source_id'] if old else '',stop)
            finally:conn.close()
        self.workflow_io_start(work,lambda sha:(self.workflow_refresh(),self.workflow_status.set('Local revision linked: '+sha[:16]+'. Review before approving.')))

    def workflow_approve(self):
        row=self.workflow_selected_doc()
        if not row:messagebox.showinfo('Select document','Select a document revision first.');return
        if not messagebox.askyesno('Approve reviewed document',f"Confirm you have reviewed this exact file revision:\n{row['filename']}\nSHA-256: {row['sha256']}\n\nThis records approval only. It does not send the document."):return
        def work(stop,progress):
            conn=connect(self.root_dir/'stability.db')
            try:approve_document(conn,row['document_key'],row['sha256'],stop)
            finally:conn.close()
        self.workflow_io_start(work,lambda _:(self.workflow_refresh(),self.workflow_status.set('Document approval recorded for its exact SHA-256.')))

    def workflow_show_document(self):
        row=self.workflow_selected_doc()
        if row:self.workflow_show_text('Document revision evidence',json.dumps(row,indent=2))

    def workflow_open_document(self):
        row=self.workflow_selected_doc()
        if not row or not row['local_path']:
            messagebox.showinfo('Link local file','Select a document and use Link local file revision first. Imported evidence does not download private files.');return
        def work(stop,progress):
            path=Path(row['local_path']).resolve(strict=True)
            return str(path),file_digest(path,stop)==row['sha256']
        def opened(value):
            path,unchanged=value
            try:
                if os.name=='nt':os.startfile(path)
                elif not webbrowser.open(Path(path).as_uri()):raise OSError('No document viewer confirmed.')
                self.workflow_status.set('Open requested in your document viewer. '+('The recorded hash matches.' if unchanged else 'CHANGED — link this new revision before approving.'))
            except OSError: self.workflow_status.set('FAILED — document viewer could not be opened. Open the linked file in your usual viewer.')
        self.workflow_io_start(work,opened)

    def workflow_show_evidence(self):
        selected=self.workflow_apps.selection()
        if not selected:return
        rows=self.conn.execute('SELECT payload_json FROM workflow_evidence WHERE source_id=? ORDER BY recorded_at,evidence_id',(selected[0],)).fetchall()
        self.workflow_show_text('Imported application evidence','Reported external evidence; not a fresh Gmail check.\n\n'+'\n\n'.join(json.dumps(json.loads(r[0]),indent=2) for r in rows))

    def workflow_show_text(self,title,value):
        dialog=tk.Toplevel(self);dialog.title(title);dialog.geometry('820x570');dialog.configure(bg=BG)
        text=tk.Text(dialog,bg=PANEL,fg=FG,wrap='word');text.pack(fill='both',expand=True,padx=12,pady=12);text.insert('1.0',value);text.configure(state='disabled')
        self.button(dialog,'Close',dialog.destroy).pack(pady=8)

    def workflow_tick(self):
        if self.workflow_closed:return
        try:
            while True:
                kind,value=self.workflow_io.events.get_nowait()
                if kind=='done':
                    callback=self.workflow_callback;self.workflow_callback=None
                    if callback:self.workflow_deliver(callback,value)
                elif kind=='error':self.workflow_status.set(str(value) if str(value).startswith('CANCELLED') else 'FAILED — '+str(value));self.workflow_callback=None
                elif kind=='progress':self.workflow_status.set(str(value))
        except queue.Empty:pass
        row=due_check(self.conn)
        wizard=getattr(self,'setup_window',None)
        setup_open=wizard is not None and wizard.winfo_exists() and not wizard.closed
        if row and not self.mail_worker.busy and not self.workflow_io.busy and not setup_open:
            if not self.mail_settings.get('account'):
                check_result(self.conn,row['id'],'BLOCKED','Gmail is not connected. Choose Set up Gmail, then Retry due mail check.')
                self.workflow_status.set('BLOCKED — connect Gmail, then retry the due session check.');self.workflow_refresh()
            else:
                check_result(self.conn,row['id'],'RUNNING','Read-only Gmail collection is running; no successful check claimed yet.')
                if not self.mail_sync_now(workflow_session_id=row['id']):
                    check_result(self.conn,row['id'],'UNKNOWN','Check could not start. Retry when the integration worker is available.')
                self.workflow_refresh()
        self.workflow_after=self.after(200,self.workflow_tick)

    def workflow_deliver(self,callback,value):
        # A worker publishes its result just before releasing its lock.
        if self.workflow_io.busy:
            self.after(10,lambda:self.workflow_deliver(callback,value));return
        if not self.workflow_closed:callback(value)

    def workflow_close(self):
        self.workflow_closed=True
        if self.workflow_after:self.after_cancel(self.workflow_after)
        self.workflow_io.close()
        with self.conn:
            self.conn.execute("UPDATE workflow_sessions SET check_state='UNKNOWN',check_detail='App closed during check; result not confirmed. Retry after reopening.' WHERE check_state='RUNNING'")
