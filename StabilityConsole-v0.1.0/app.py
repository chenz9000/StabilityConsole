"""Stability Console v0.1.0. No background network collection or auto-sending."""
import logging
import sys
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
import webbrowser
from core import (VERSION,STATUSES,PRIORITIES,data_dir,preflight,connect,add_application,update_application,
    applications,add_task,tasks,set_task_done,due_items,metrics,search_urls,export_csv,backup)

BG='#150e0e'; PANEL='#241716'; FIELD='#352221'; RED='#a92e2c'; GOLD='#d6a36a'; FG='#f5e9e3'; MUTED='#b7a5a0'

class Window(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('STABILITY CONSOLE | Local Career & Life Tracker v'+VERSION)
        self.geometry('1120x735');self.minsize(840,570);self.configure(bg=BG)
        self.root_dir=data_dir(); self.root_dir.mkdir(parents=True,exist_ok=True)
        self.conn=connect(self.root_dir/'stability.db')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.configure_styles()
        head=tk.Frame(self,bg=BG);head.pack(fill='x',padx=18,pady=(14,5))
        tk.Label(head,text='STABILITY CONSOLE',font=('Segoe UI',20,'bold'),bg=BG,fg=GOLD).pack(side='left')
        tk.Label(head,text='PRIVATE • OFFLINE • EVIDENCE-LED',font=('Segoe UI',9),bg=BG,fg=MUTED).pack(side='right')
        self.notebook=ttk.Notebook(self);self.notebook.pack(fill='both',expand=True,padx=16,pady=8)
        self.overview=ttk.Frame(self.notebook);self.apps=ttk.Frame(self.notebook);self.todo=ttk.Frame(self.notebook);self.discovery=ttk.Frame(self.notebook)
        for page,name in [(self.overview,'Overview'),(self.apps,'Applications'),(self.todo,'Daily actions'),(self.discovery,'Browser job search')]:self.notebook.add(page,text=name)
        self.build_overview();self.build_apps();self.build_tasks();self.build_discovery()
        self.status=tk.StringVar(value='Local database: '+str(self.root_dir/'stability.db'))
        tk.Label(self,textvariable=self.status,bg=BG,fg=MUTED,anchor='w',font=('Segoe UI',9)).pack(fill='x',padx=18,pady=(0,8))
        self.refresh_all()
        if not (self.root_dir/'readme_seen.flag').exists():
            self.after(250,self.first_run)
    def configure_styles(self):
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('TFrame',background=BG)
        style.configure('TNotebook',background=BG,borderwidth=0)
        style.configure('TNotebook.Tab',background=PANEL,foreground=FG,padding=(18,10),font=('Segoe UI',10))
        style.map('TNotebook.Tab',background=[('selected',RED)])
        style.configure('Treeview',background=PANEL,foreground=FG,fieldbackground=PANEL,rowheight=30,borderwidth=0,font=('Segoe UI',10))
        style.map('Treeview',background=[('selected',RED)])
        style.configure('Treeview.Heading',background=FIELD,foreground=GOLD,font=('Segoe UI',10,'bold'))
        style.configure('TCombobox',fieldbackground=FIELD,background=FIELD,foreground='#211515')
        style.configure('TScrollbar',background=PANEL)
    def button(self,parent,text,command):
        return tk.Button(parent,text=text,command=command,bg=RED,fg='white',activebackground='#cf463d',activeforeground='white',relief='flat',padx=15,pady=9,font=('Segoe UI',10,'bold'),cursor='hand2')
    def label(self,parent,text,large=False):
        return tk.Label(parent,text=text,bg=BG,fg=GOLD if large else FG,font=('Segoe UI',14 if large else 10,'bold' if large else 'normal'),anchor='w')
    def build_overview(self):
        f=self.overview
        self.label(f,'YOUR NEXT REAL ACTION',True).pack(fill='x',padx=14,pady=12)
        self.metric_label=tk.Label(f,bg=PANEL,fg=FG,font=('Segoe UI',13),padx=16,pady=15,anchor='w',justify='left')
        self.metric_label.pack(fill='x',padx=14)
        self.label(f,'Due or overdue follow-ups and actions',True).pack(fill='x',padx=14,pady=(20,8))
        self.due_box=tk.Listbox(f,bg=PANEL,fg=FG,selectbackground=RED,relief='flat',font=('Segoe UI',11),height=13)
        self.due_box.pack(fill='both',expand=True,padx=14,pady=(0,12))
        buttons=tk.Frame(f,bg=BG);buttons.pack(fill='x',padx=14,pady=(0,12))
        self.button(buttons,'Add application',lambda:self.notebook.select(self.apps)).pack(side='left',padx=(0,8))
        self.button(buttons,'Add daily action',lambda:self.notebook.select(self.todo)).pack(side='left')
        self.button(buttons,'Backup database',self.save_backup).pack(side='right')
    def build_apps(self):
        f=self.apps;top=tk.Frame(f,bg=BG);top.pack(fill='x',padx=12,pady=10)
        self.label(top,'APPLICATION REGISTER',True).pack(side='left')
        self.app_filter=tk.StringVar();tk.Entry(top,textvariable=self.app_filter,width=27,bg=FIELD,fg=FG,insertbackground=FG,relief='flat').pack(side='right',padx=8,ipady=7)
        tk.Label(top,text='Filter:',bg=BG,fg=MUTED).pack(side='right')
        self.app_filter.trace_add('write',lambda *_:self.refresh_apps())
        frame=tk.Frame(f,bg=BG);frame.pack(fill='both',expand=True,padx=12)
        cols=('title','employer','area','status','due_date','cv_version')
        self.app_tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='browse')
        for col,label,width in [('title','Position',235),('employer','Employer',150),('area','Area',130),('status','Status',150),('due_date','Follow-up',100),('cv_version','CV used',120)]:
            self.app_tree.heading(col,text=label);self.app_tree.column(col,width=width,minwidth=70)
        self.app_tree.pack(fill='both',expand=True,side='left')
        ttk.Scrollbar(frame,orient='vertical',command=self.app_tree.yview).pack(side='right',fill='y')
        self.app_tree.bind('<Double-1>',lambda e:self.edit_application())
        buttons=tk.Frame(f,bg=BG);buttons.pack(fill='x',padx=12,pady=12)
        self.button(buttons,'New application',lambda:self.application_dialog()).pack(side='left',padx=(0,8))
        self.button(buttons,'Edit selected',self.edit_application).pack(side='left',padx=(0,8))
        self.button(buttons,'Open source',self.open_source).pack(side='left',padx=(0,8))
        self.button(buttons,'Export CSV',self.export).pack(side='right')
    def selected_application(self):
        selection=self.app_tree.selection()
        if not selection: messagebox.showinfo('Select application','Select one listing first.');return None
        return self.conn.execute('SELECT * FROM applications WHERE id=?',(int(selection[0]),)).fetchone()
    def application_dialog(self,old=None):
        dialog=tk.Toplevel(self);dialog.title('Edit application' if old else 'New application');dialog.geometry('610x620');dialog.configure(bg=BG);dialog.transient(self);dialog.grab_set()
        fields=[('title','Job title *'),('employer','Employer'),('area','Location'),('url','Listing / application URL'),('status','Status'),('cv_version','CV version actually used'),('due_date','Follow-up date (YYYY-MM-DD)'),('applied_on','Sent date (YYYY-MM-DD)'),('notes','Notes and special instructions')]
        controls={}
        for idx,(key,label) in enumerate(fields):
            tk.Label(dialog,text=label,bg=BG,fg=FG,anchor='w').grid(row=idx,column=0,padx=14,pady=7,sticky='w')
            value=old[key] if old else ('Discovered' if key=='status' else '')
            if key=='status':
                widget=ttk.Combobox(dialog,values=STATUSES,state='readonly',width=35);widget.set(value)
            elif key=='notes':
                widget=tk.Text(dialog,width=40,height=5,bg=FIELD,fg=FG,insertbackground=FG);widget.insert('1.0',value)
            else:
                widget=tk.Entry(dialog,width=39,bg=FIELD,fg=FG,insertbackground=FG,relief='flat');widget.insert(0,value)
            widget.grid(row=idx,column=1,padx=10,pady=7,sticky='ew');controls[key]=widget
        dialog.columnconfigure(1,weight=1)
        def save():
            data={k:(w.get('1.0','end').strip() if k=='notes' else w.get().strip()) for k,w in controls.items()}
            try:
                if old:update_application(self.conn,old['id'],**data)
                else:add_application(self.conn,**data)
                self.refresh_all();dialog.destroy();self.status.set('Application saved locally at '+datetime.now().strftime('%H:%M:%S'))
            except (ValueError,OSError) as exc:messagebox.showerror('Validation failed',str(exc),parent=dialog)
            except Exception:
                logging.exception('Application save failed');messagebox.showerror('Save failed','Database error. Check logs; record not confirmed saved.',parent=dialog)
        self.button(dialog,'Save application',save).grid(row=len(fields),column=1,pady=15,sticky='e',padx=12)
        controls['title'].focus_set()
    def edit_application(self):
        row=self.selected_application()
        if row:self.application_dialog(row)
    def open_source(self):
        row=self.selected_application()
        if row:
            if not row['url']:messagebox.showinfo('Missing URL','No source URL has been recorded for this application.');return
            webbrowser.open(row['url'])
    def build_tasks(self):
        f=self.todo;self.label(f,'DAILY ACTIONS',True).pack(fill='x',padx=12,pady=12)
        frame=tk.Frame(f,bg=BG);frame.pack(fill='both',expand=True,padx=12)
        cols=('title','category','priority','due_date','done')
        self.task_tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='browse')
        for col,label,width in [('title','Action',400),('category','Area of life',140),('priority','Priority',100),('due_date','Due',120),('done','Done',70)]:
            self.task_tree.heading(col,text=label);self.task_tree.column(col,width=width,minwidth=65)
        self.task_tree.pack(fill='both',expand=True,side='left')
        ttk.Scrollbar(frame,orient='vertical',command=self.task_tree.yview).pack(side='right',fill='y')
        buttons=tk.Frame(f,bg=BG);buttons.pack(fill='x',padx=12,pady=12)
        self.button(buttons,'New action',self.task_dialog).pack(side='left',padx=(0,8))
        self.button(buttons,'Mark done / reopen',self.toggle_task).pack(side='left')
        self.show_done=tk.BooleanVar(value=False)
        tk.Checkbutton(buttons,text='Show completed',variable=self.show_done,command=self.refresh_tasks,bg=BG,fg=FG,selectcolor=FIELD,activebackground=BG,activeforeground=FG).pack(side='right')
    def task_dialog(self):
        d=tk.Toplevel(self);d.title('New daily action');d.geometry('560x360');d.configure(bg=BG);d.transient(self);d.grab_set()
        fields={}
        for i,(key,label,default) in enumerate([('title','Action *',''),('category','Category (Work / Personal / Health)','Personal'),('priority','Priority','Normal'),('due_date','Due date YYYY-MM-DD','')]):
            tk.Label(d,text=label,bg=BG,fg=FG).grid(row=i,column=0,padx=12,pady=12,sticky='w')
            if key=='priority':w=ttk.Combobox(d,values=PRIORITIES,state='readonly',width=26);w.set(default)
            else:w=tk.Entry(d,width=29,bg=FIELD,fg=FG,insertbackground=FG);w.insert(0,default)
            w.grid(row=i,column=1,padx=12,pady=12);fields[key]=w
        def save():
            try:
                add_task(self.conn,**{k:w.get().strip() for k,w in fields.items()});self.refresh_all();d.destroy()
            except ValueError as exc:messagebox.showerror('Check input',str(exc),parent=d)
            except Exception:logging.exception('Task save failed');messagebox.showerror('Save failed','Review logs.',parent=d)
        self.button(d,'Save action',save).grid(row=4,column=1,pady=14)
    def toggle_task(self):
        sel=self.task_tree.selection()
        if not sel:messagebox.showinfo('Select action','Select an action first.');return
        row=self.conn.execute('SELECT * FROM tasks WHERE id=?',(int(sel[0]),)).fetchone()
        if row:set_task_done(self.conn,row['id'],not row['done']);self.refresh_all()
    def build_discovery(self):
        f=self.discovery;self.label(f,'SEARCH IN YOUR OWN BROWSER',True).pack(fill='x',padx=12,pady=(16,8))
        tk.Label(f,text='These buttons open real searches in Chrome/Edge or your default browser. They do NOT scrape, verify, or import listings.\nOnly add an application after reviewing its original advertisement.',bg=BG,fg=MUTED,justify='left',font=('Segoe UI',10)).pack(fill='x',padx=12,pady=8)
        self.area_var=tk.StringVar(value='Knysna, George, Plettenberg Bay')
        self.keyword_var=tk.StringVar()
        for label,var in [('Areas, comma-separated',self.area_var),('Keywords (optional, blank = all categories)',self.keyword_var)]:
            self.label(f,label).pack(fill='x',padx=12,pady=(10,3))
            tk.Entry(f,textvariable=var,bg=FIELD,fg=FG,insertbackground=FG,relief='flat',font=('Segoe UI',11)).pack(fill='x',padx=12,ipady=10)
        buttons=tk.Frame(f,bg=BG);buttons.pack(fill='x',padx=12,pady=14)
        self.button(buttons,'Prepare browser searches',self.prepare_searches).pack(side='left')
        self.search_box=tk.Listbox(f,bg=PANEL,fg=FG,relief='flat',font=('Segoe UI',11),height=11,selectbackground=RED)
        self.search_box.pack(fill='both',expand=True,padx=12,pady=8)
        self.search_box.bind('<Double-1>',lambda e:self.open_search())
        self.button(f,'Open selected browser search',self.open_search).pack(anchor='e',padx=12,pady=12)
        self.links=[]
    def prepare_searches(self):
        try:self.links=search_urls(self.area_var.get(),self.keyword_var.get())
        except ValueError as exc:messagebox.showerror('Missing areas',str(exc));return
        self.search_box.delete(0,'end')
        for area,provider,url in self.links:self.search_box.insert('end',f'{area}  |  {provider}')
        self.status.set(f'{len(self.links)} browser search links prepared. No jobs retrieved or verified.')
    def open_search(self):
        idx=self.search_box.curselection()
        if not idx:messagebox.showinfo('Select search','Prepare searches and select one result first.');return
        area,provider,url=self.links[idx[0]]
        try:
            opened=webbrowser.open(url)
            self.status.set(f'Browser open requested: {provider}, {area}. Results not imported or verified.')
            if not opened:messagebox.showwarning('Browser unavailable','Could not confirm a browser opened. URL can be copied from the search list.')
        except Exception as exc:messagebox.showerror('Browser launch failed',str(exc))
    def refresh_apps(self):
        for row in self.app_tree.get_children():self.app_tree.delete(row)
        for item in applications(self.conn,self.app_filter.get()):self.app_tree.insert('', 'end',iid=str(item['id']),values=tuple(item[c] for c in ('title','employer','area','status','due_date','cv_version')))
    def refresh_tasks(self):
        for row in self.task_tree.get_children():self.task_tree.delete(row)
        for item in tasks(self.conn,self.show_done.get()):self.task_tree.insert('','end',iid=str(item['id']),values=(item['title'],item['category'],item['priority'],item['due_date'],'Yes' if item['done'] else 'No'))
    def refresh_overview(self):
        info=metrics(self.conn);a,b=due_items(self.conn)
        self.metric_label.config(text=f"Applications recorded: {info['total']}      Applied or progressed: {info['applied']}      Interviews: {info['interviews']}      Open actions: {info['tasks']}")
        self.due_box.delete(0,'end')
        for item in a:self.due_box.insert('end',f"ACTION  |  {item['due_date']}  |  {item['title']}")
        for item in b:self.due_box.insert('end',f"FOLLOW UP  |  {item['due_date']}  |  {item['title']} ({item['employer']})")
        if not a and not b:self.due_box.insert('end','No overdue actions recorded. Add your next practical step.')
    def refresh_all(self):self.refresh_apps();self.refresh_tasks();self.refresh_overview()
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV files','*.csv')],initialfile='applications-export.csv')
        if path:
            try:export_csv(self.conn,path);messagebox.showinfo('Export saved','Application CSV saved to:\n'+path)
            except Exception:logging.exception('Export failed');messagebox.showerror('Export failed','Could not save export. See logs.')
    def save_backup(self):
        path=filedialog.asksaveasfilename(defaultextension='.db',filetypes=[('SQLite database','*.db')],initialfile='stability-backup-'+date.today().isoformat()+'.db')
        if path:
            try:backup(self.conn,path);messagebox.showinfo('Backup complete','Database backup saved:\n'+path)
            except Exception:logging.exception('Backup failed');messagebox.showerror('Backup failed','See logs. Backup not confirmed.')
    def first_run(self):
        messagebox.showinfo('First-run information','STABILITY CONSOLE v'+VERSION+'\n\nThis application stores your records locally.\nIt never sends CVs or submits jobs.\nBrowser job searches open in your default browser for manual review.\n\nBack up your database regularly using the Overview button.')
        try:(self.root_dir/'readme_seen.flag').write_text('shown',encoding='utf-8')
        except OSError: pass
    def close(self):
        self.conn.close();self.destroy()

def main():
    root=data_dir();results=preflight(root)
    for status,name,detail in results:print(f'{status}: {name}: {detail}')
    if any(status=='FAIL' for status,_,_ in results):return 2
    logging.basicConfig(filename=str(root/'stability.log'),level=logging.ERROR,format='%(asctime)s %(levelname)s %(message)s')
    try:app=Window();app.mainloop();return 0
    except Exception:
        logging.exception('Application startup failed');raise
if __name__=='__main__':sys.exit(main())
