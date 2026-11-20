import os
import tempfile
import json
import time
from pathlib import Path
from core import connect,add_application,add_task
from app import Window
from datetime import date
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from job_workflow import start_session,complete_session
from theme import ACCENT

def capture(root, name):
    """Optional screenshots contain only the synthetic records below."""
    target=os.environ.get('STABILITY_SCREENSHOT_DIR')
    if not target:return
    from PIL import ImageGrab
    root.update_idletasks();root.update()
    # Let the window manager paint before capturing the actual Tk window.
    root.after(120,root.quit);root.mainloop()
    root.lift();root.update()
    x,y=root.winfo_rootx(),root.winfo_rooty()
    path=Path(target);path.mkdir(parents=True,exist_ok=True)
    ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(path/(name+'.png'))

def visible_button(root, text):
    pending=[root]
    while pending:
        widget=pending.pop()
        if widget.winfo_class()=='Button' and widget.cget('text')==text:
            assert widget.winfo_ismapped(), text+' is hidden'
            assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height(),text+' is clipped'
            assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width(),text+' is clipped'
            return
        pending.extend(widget.winfo_children())
    raise AssertionError('Missing button: '+text)

with tempfile.TemporaryDirectory() as td:
    os.environ['STABILITY_CONSOLE_DATA']=td
    Path(td,'readme_seen.flag').write_text('test')
    root=Window()
    assert root.winfo_exists()
    app_id=add_application(root.conn,'Technician','Example Employer','Knysna',url='https://example.org/jobs/1',due_date=date.today().isoformat())
    task_id=add_task(root.conn,'Follow up email',due_date=date.today().isoformat())
    root.refresh_all()
    root.status.set('DEMONSTRATION DATA / GUI verification — temporary test database')
    assert root.metric_values['total'].get()=='1'
    assert root.app_tree.exists(str(app_id))
    assert root.task_tree.exists(str(task_id))
    assert root.due_box.size()==2
    root.area_var.set('Knysna, George')
    root.prepare_searches()
    assert len(root.links)==4
    assert root.search_box.size()==4
    for page,control in root.nav_buttons.items():
        control.invoke();root.update()
        assert root.notebook.select()==page
        assert control.cget('fg')==ACCENT
        assert control.winfo_ismapped()
    root.notebook.select(root.overview);root.update()
    capture(root,'01-overview')
    root.notebook.select(root.apps);root.update()
    root.app_tree.selection_set(str(app_id))
    capture(root,'02-applications')
    root.notebook.select(root.gmail);root.update()
    capture(root,'03-gmail')
    root.mail_wizard();root.update()
    assert root.setup_window.winfo_exists()
    capture(root.setup_window,'04-gmail-setup')
    root.setup_window.dismiss();root.update()
    root.application_dialog();root.update()
    dialog=next(w for w in root.winfo_children() if w.winfo_class()=='Toplevel' and w.winfo_exists())
    capture(dialog,'05-application-form')
    dialog.destroy()
    report={'schema_version':1,'namespace':'gui-test','report_id':'gui-session','account':'candidate@example.org',
        'applications':[{'external_id':'GUI-1','title':'Service Desk','employer':'Example Employer','status':'SENT',
            'url':'https://example.org/jobs/2','evidence':[{'kind':'submission','message_id':'gui-message','thread_id':'gui-thread'}]},
            {'external_id':'GUI-2','title':'Technician draft','employer':'Other Employer','status':'DRAFT'}],
        'profile':[{'name':'Availability','value':'Immediately','state':'CONFIRMED','source':'Test review'}],
        'documents':[{'document_key':'profile','filename':'profile.docx','sha256':'a'*64,'state':'APPROVED'}]}
    path=Path(td,'session.json');path.write_text(json.dumps(report))
    def import_from_ui():
        with patch('workflow_panel.filedialog.askopenfilename',return_value=str(path)),patch('workflow_panel.messagebox.askyesno',return_value=True):
            root.workflow_import()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                root.update();time.sleep(.02)
                if not root.workflow_io.busy and root.workflow_callback is None:break
        assert root.conn.execute('SELECT count(*) FROM workflow_links').fetchone()[0]==2
    import_from_ui();import_from_ui()
    assert len(root.workflow_apps.get_children())==2
    assert len(root.workflow_facts.get_children())==1
    assert len(root.workflow_docs.get_children())==1
    root.notebook.select(root.workflow);root.update()
    capture(root,'06-workflow')
    assert root.conn.execute('SELECT count(*) FROM applications').fetchone()[0]==3
    past=datetime.now(timezone.utc)-timedelta(minutes=6)
    ident=start_session(root.conn,at=past)
    complete_session(root.conn,ident,at=past)
    root.workflow_tick();root.update()
    assert root.conn.execute('SELECT check_state FROM workflow_sessions WHERE id=?',(ident,)).fetchone()[0]=='BLOCKED'
    root.workflow_refresh();root.notebook.select(root.workflow);root.update_idletasks();root.update()
    root.geometry('%dx%d'%root.minsize());root.update()
    visible_button(root,'Import session report')
    capture(root,'07-minimum-workflow')
    root.notebook.select(root.gmail);root.update()
    visible_button(root,'Review selected message')
    capture(root,'08-minimum-gmail')
    root.notebook.select(root.overview);root.update()
    visible_button(root,'Add application')
    capture(root,'09-minimum-overview')
    root.update_idletasks()
    root.update()
    root.close()
    db=connect(Path(td)/'stability.db')
    assert db.execute('select count(*) from applications').fetchone()[0]==3
    db.close()
    reopened=Window();reopened.update();assert len(reopened.workflow_apps.get_children())==2;reopened.close()
    print('GUI SMOKE PASS: real Tk sidebar navigation, Matrix dashboard, forms and Gmail setup, UI report import twice, profile/documents, delayed-check blocker, shutdown and restart persistence')
