import unittest,tempfile,json
from pathlib import Path
from backend.db import connect,one
from backend.services import mutate

class BaselineEdits(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite')
  self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target,start,end,status) VALUES ('D3','V1',.03,2,.05,'2026-01-01','2026-03-31','ACTIVA')")
  self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target,start,end,status) VALUES ('D3','V2',.04,3,.06,'2026-04-01',NULL,'ACTIVA')")
  self.db.execute("INSERT INTO periods(period,status,snapshot) VALUES ('2026-01','CERRADO','original')")
  self.db.execute("INSERT INTO periods(period,status) VALUES ('2026-02','EN REVISIÓN')")
  self.data=dict(id=1,slope=.035,intercept=4,target=.05,max_tank_gallons=5,start='2026-01-01',end='2026-03-31',reason='Corrección',actor='Prueba')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_revision_preserves_original_and_closed_snapshot(self):
  mutate(self.db,'edit_baseline',self.data)
  original=one(self.db,'SELECT * FROM baselines WHERE id=1')
  self.assertEqual(original['slope'],.03);self.assertEqual(original['active'],0)
  new=one(self.db,"SELECT * FROM baselines WHERE version='V1-R2'")
  self.assertEqual(new['slope'],.035);self.assertEqual(new['active'],1)
  self.assertEqual(new['max_tank_gallons'],5);self.assertIsNone(original['max_tank_gallons'])
  self.assertEqual(one(self.db,"SELECT status,snapshot FROM periods WHERE period='2026-01'"),dict(status='CERRADO',snapshot='original'))
  self.assertEqual(one(self.db,"SELECT status FROM periods WHERE period='2026-02'")['status'],'BORRADOR')
  audit=one(self.db,"SELECT original,value FROM overrides WHERE field='revision'")
  self.assertEqual(json.loads(audit['original'])['id'],1);self.assertEqual(json.loads(audit['value'])['id'],new['id'])
 def test_overlap_inclusive_boundary_and_open_end(self):
  for end in ['2026-04-01','']:
   with self.assertRaisesRegex(ValueError,'D3.*V2'):mutate(self.db,'edit_baseline',{**self.data,'end':end})
  self.assertEqual(one(self.db,'SELECT count(*) n FROM baselines')['n'],2)
  self.assertEqual(one(self.db,'SELECT active FROM baselines WHERE id=1')['active'],1)
 def test_invalid_dates_and_missing_audit(self):
  for changes in [dict(start='2026-05-01'),dict(actor=''),dict(start=''),dict(target='')]:
   with self.assertRaises(ValueError):mutate(self.db,'edit_baseline',{**self.data,**changes})
 def test_activation_has_same_conflict_guard(self):
  self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target) VALUES ('D3','V3',.03,2,.05)")
  with self.assertRaisesRegex(ValueError,'D3.*V1'):mutate(self.db,'baseline',{**self.data,'id':3})
