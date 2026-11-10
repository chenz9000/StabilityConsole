import csv
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from core import *

class CoreTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.conn=connect(self.path)
    def tearDown(self):self.conn.close();self.tmp.cleanup()
    def test_persist_and_status(self):
        ident=add_application(self.conn,'IT Support','Employer A','Knysna',url='https://example.org/job',cv_version='Tech v2')
        update_application(self.conn,ident,status='Applied',applied_on='2026-11-10')
        self.conn.close();self.conn=connect(self.path)
        row=applications(self.conn)[0];self.assertEqual(row['status'],'Applied');self.assertEqual(row['cv_version'],'Tech v2')
        self.assertEqual(self.conn.execute('select count(*) from events').fetchone()[0],2)
    def test_reject_invalid_and_no_mutation(self):
        with self.assertRaises(ValueError):add_application(self.conn,'Job',url='file:///etc/passwd')
        self.assertEqual(len(applications(self.conn)),0)
        with self.assertRaises(ValueError):add_application(self.conn,'Job',due_date='today')
    def test_due_and_completion(self):
        yesterday=(date.today()-timedelta(days=1)).isoformat()
        ident=add_task(self.conn,'Make a call',due_date=yesterday)
        add_application(self.conn,'Helpdesk',due_date=yesterday)
        a,b=due_items(self.conn);self.assertEqual((len(a),len(b)),(1,1))
        set_task_done(self.conn,ident,True)
        self.assertEqual(len(due_items(self.conn)[0]),0)
    def test_browser_urls_are_location_specific(self):
        links=search_urls('Knysna, George; Knysna\nPlettenberg Bay')
        self.assertEqual(len(links),6)
        self.assertIn('George',links[2][2]);self.assertEqual(links[2][1],'Google web search')
        with self.assertRaises(ValueError):search_urls('')
    def test_csv_backup(self):
        add_application(self.conn,'Network admin','Test','George')
        target=Path(self.tmp.name)/'applications.csv';export_csv(self.conn,target)
        with target.open(encoding='utf-8-sig',newline='') as fp:self.assertEqual(list(csv.DictReader(fp))[0]['title'],'Network admin')
        b=Path(self.tmp.name)/'backup.db';backup(self.conn,b)
        restore=connect(b)
        try:self.assertEqual(len(applications(restore)),1)
        finally:restore.close()
    def test_metrics_conservative(self):
        add_application(self.conn,'Job',status='Discovered');self.assertEqual(metrics(self.conn)['applied'],0)
        add_application(self.conn,'Job 2',status='Applied');self.assertEqual(metrics(self.conn)['applied'],1)

if __name__=='__main__':unittest.main()
