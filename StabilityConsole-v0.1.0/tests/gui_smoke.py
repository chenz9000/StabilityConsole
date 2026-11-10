import os
import tempfile
from pathlib import Path
from core import connect,add_application,add_task
from app import Window
from datetime import date

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
    root.update_idletasks()
    root.update()
    root.close()
    db=connect(Path(td)/'stability.db')
    assert db.execute('select count(*) from applications').fetchone()[0]==1
    db.close()
    print('GUI SMOKE PASS: initialized, inserted rows, overview refreshed, browser links rendered, restarted DB persistence')
