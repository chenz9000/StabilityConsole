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

with tempfile.TemporaryDirectory() as td:
    os.environ['STABILITY_CONSOLE_DATA']=td
    Path(td,'readme_seen.flag').write_text('test')
    root=Window()
    assert root.winfo_exists()
    app_id=add_application(root.conn,'Technician','Example Employer','Knysna',url='https://example.org/jobs/1',due_date=date.today().isoformat())
    task_id=add_task(root.conn,'Follow up email',due_date=date.today().isoformat())
    root.refresh_all()
    assert root.app_tree.exists(str(app_id))
    assert root.task_tree.exists(str(task_id))
    assert root.due_box.size()==2
    root.area_var.set('Knysna, George')
    root.prepare_searches()
    assert len(root.links)==4
    assert root.search_box.size()==4
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
    assert root.conn.execute('SELECT count(*) FROM applications').fetchone()[0]==3
    past=datetime.now(timezone.utc)-timedelta(minutes=6)
    ident=start_session(root.conn,at=past)
    complete_session(root.conn,ident,at=past)
    root.workflow_tick();root.update()
    assert root.conn.execute('SELECT check_state FROM workflow_sessions WHERE id=?',(ident,)).fetchone()[0]=='BLOCKED'
    root.workflow_refresh();root.notebook.select(root.workflow);root.update_idletasks();root.update()
    root.update_idletasks()
    root.update()
    root.close()
    db=connect(Path(td)/'stability.db')
    assert db.execute('select count(*) from applications').fetchone()[0]==3
    db.close()
    reopened=Window();reopened.update();assert len(reopened.workflow_apps.get_children())==2;reopened.close()
    print('GUI SMOKE PASS: real Tk widgets, UI report import twice, profile/documents, delayed-check blocker, shutdown and restart persistence')
