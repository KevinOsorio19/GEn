import unittest,tempfile,json
from pathlib import Path
import openpyxl
from backend.engine import calculate
from backend.db import connect,rows,one
from backend.importers import import_file,get_vehicle,assign
from backend.services import mutate,process,state
B={'slope':.03,'intercept':2,'target':.05,'version':'V1'}
def tank(day,odo,g=10,month='08',id=None):return {'id':id or day,'date':f'2026-{month}-{day:02} 10:00:00','odometer':odo,'gallons':g,'cost':g*10000}
class EngineTests(unittest.TestCase):
 def test_01_four_tanks(self):
  r=calculate([tank(1,1000,8),tank(8,1300,11),tank(16,1600,10),tank(25,1900,12)],baseline=B)
  self.assertEqual(r['gallons'],33);self.assertEqual(r['km'],900);self.assertAlmostEqual(r['ic'],(29-33)/29)
 def test_02_two_tanks(self):
  r=calculate([tank(2,1000,8),tank(9,1400,12)],baseline=B);self.assertEqual(r['gallons'],12);self.assertEqual(r['km'],400)
 def test_03_one_with_history(self):
  r=calculate([tank(18,50420,15)],tank(31,50000,10,'07'),baseline=B);self.assertEqual(r['km'],420);self.assertEqual(r['gallons'],15)
 def test_04_one_without_history(self):
  r=calculate([tank(18,50420)],tso={'km':500},baseline=B);self.assertIsNone(r['gallons']);self.assertIsNone(r['km']);self.assertEqual(r['quality'],'INFORMACIÓN INSUFICIENTE')
 def test_05_negative(self):self.assertIsNone(calculate([tank(1,1000),tank(20,900)])['km'])
 def test_06_repeated(self):self.assertIsNone(calculate([tank(1,1000),tank(20,1000)])['km'])
 def test_07_large_distance(self):self.assertIsNone(calculate([tank(1,1000),tank(31,18000)])['km'])
 def test_08_tso_fallback(self):
  r=calculate([tank(1,1000),tank(20,900)],tso={'km':450},baseline=B);self.assertEqual(r['source'],'TSO');self.assertEqual(r['terpel_km'],-100);self.assertEqual(r['km'],450)
 def test_09_both_invalid(self):self.assertIsNone(calculate([tank(1,1000),tank(20,900)],tso={'km':-1})['km'])
 def test_10_new_vehicle(self):self.assertEqual(calculate([tank(1,1000)])['quality'],'INFORMACIÓN INSUFICIENTE')
 def test_15_no_tanks(self):self.assertIsNone(calculate([],tso={'km':250})['gallons'])
 def test_16_missing_baseline(self):
  r=calculate([tank(1,1000),tank(20,1500)]);self.assertEqual(r['km'],500);self.assertIsNone(r['ic']);self.assertEqual(r['quality'],'REQUIERE REVISIÓN')
 def test_17_manual(self):
  r=calculate([tank(1,1000),tank(20,900)],baseline=B,override={'km':500,'reason':'corrección','source':'MANUAL'});self.assertEqual(r['source'],'MANUAL');self.assertEqual(r['km'],500)
 def test_valid_terpel_priority(self):self.assertEqual(calculate([tank(1,1000),tank(20,1500)],tso={'km':800})['km'],500)
 def test_internal_odometer_jump(self):self.assertIsNone(calculate([tank(1,1000),tank(8,100000),tank(20,1500)])['km'])
 def test_zero_theoretical(self):self.assertIsNone(calculate([tank(1,1000),tank(20,1500)],baseline={'slope':0,'intercept':0,'target':0})['ic'])
class PersistenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def workbook(self,rows,name='input.xlsx'):
  p=Path(self.tmp.name)/name;w=openpyxl.Workbook()
  for r in rows:w.active.append(r)
  w.save(p);return p
 def terpel(self,records=None,name='terpel.xlsx'):
  return self.workbook([['Placa ','Fecha','Cantidad','Total Venta','Kilometraje ','Estación ','Unidad de Medida','Identificador de la Venta'],*(records or [['ABC123','2026-08-01 10:00:00',10,100000,1000,'EDS','UGL','1'],['ABC123','2026-08-20 10:00:00',12,120000,1400,'EDS','UGL','2']])],name)
 def test_11_duplicate_tank(self):
  p=self.terpel([['ABC123','2026-08-01 10:00:00',10,100000,1000,'EDS','UGL','1']]*2)
  r=import_file(self.db,p,'terpel','2026-08');self.assertEqual(r['imported'],1);self.assertEqual(r['duplicates'],1)
 def test_12_same_file(self):
  p=self.terpel();import_file(self.db,p,'terpel','2026-08');r=import_file(self.db,p,'terpel','2026-08');self.assertTrue(r['already_imported']);self.assertEqual(len(rows(self.db,'SELECT * FROM transactions')),2)
 def test_13_unknown_vehicle(self):
  r=import_file(self.db,self.terpel(),'terpel','2026-08');self.assertEqual(r['unknown'],2);self.assertEqual(one(self.db,'SELECT known FROM vehicles')['known'],0);self.assertEqual(len(rows(self.db,'SELECT * FROM issues')),2)
 def test_14_project_change(self):
  v=get_vehicle(self.db,'ABC123',True);assign(self.db,v['id'],'A','2026-01-01');assign(self.db,v['id'],'B','2026-08-16')
  a=rows(self.db,'SELECT * FROM assignments ORDER BY start');self.assertEqual(a[0]['end'],'2026-08-15');self.assertEqual(a[1]['start'],'2026-08-16')
 def prepare(self):
  import_file(self.db,self.terpel(),'terpel','2026-08');v=get_vehicle(self.db,'ABC123');self.db.execute("UPDATE vehicles SET known=1,energy_group='D3' WHERE id=?",(v['id'],));assign(self.db,v['id'],'A','2026-08-01');self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target,start,end,status) VALUES ('D3','V1',.03,2,.05,'2026-01-01','2026-12-31','ACTIVA')");process(self.db,'2026-08');return v
 def test_17_override_audit(self):
  v=self.prepare();mutate(self.db,'override',{'period':'2026-08','vehicle_id':v['id'],'source':'MANUAL','km':500,'reason':'Soporte odómetro','actor':'Prueba'})
  a=one(self.db,"SELECT * FROM overrides WHERE entity='result'");self.assertEqual(json.loads(a['before_result'])['km'],400);self.assertEqual(json.loads(a['after_result'])['km'],500)
 def test_18_baseline_versions(self):
  v=self.prepare();self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target,start,status) VALUES ('D3','V2',.02,3,.04,'2027-01-01','ACTIVA')");process(self.db,'2026-08');r=state(self.db,'2026-08')['results'][0];self.assertEqual(r['baseline']['version'],'V1')
 def test_tso_fallback_through_database(self):
  self.prepare()
  self.db.execute('UPDATE transactions SET odometer=900 WHERE id=2')
  v=one(self.db,'SELECT id FROM vehicles')
  p=self.workbook([['Unidad','Kms','Galones','Desde','Hasta'],['ABC123',600,12,'2026-08-01','2026-08-20']],'tso.xlsx')
  import_file(self.db,p,'efficiency','2026-08');process(self.db,'2026-08')
  r=state(self.db,'2026-08')['results'][0]
  self.assertEqual(r['source'],'TSO');self.assertEqual(r['km'],600)
 def test_closed_snapshot(self):
  self.prepare();mutate(self.db,'close',{'period':'2026-08'});before=state(self.db,'2026-08');self.db.execute("UPDATE vehicles SET energy_group='OTHER'");after=state(self.db,'2026-08');self.assertEqual(before['results'],after['results'])
  with self.assertRaises(ValueError):process(self.db,'2026-08')
  with self.assertRaises(ValueError):import_file(self.db,self.terpel(),'terpel','2026-08')
 def test_period_validation(self):
  r=import_file(self.db,self.terpel(),'terpel','2026-09');self.assertEqual(r['imported'],0);self.assertEqual(r['warnings'],2)
 def test_cross_file_duplicate(self):
  import_file(self.db,self.terpel(),'terpel','2026-08');p=self.terpel(name='second.xlsx');w=openpyxl.load_workbook(p);w.active['I1']='Extra';w.save(p)
  r=import_file(self.db,p,'terpel','2026-08');self.assertEqual(r['duplicates'],2)
 def test_overlapping_baseline(self):
  self.prepare();self.db.execute("INSERT INTO baselines(energy_group,version,slope,intercept,target) VALUES ('D3','V2',.02,3,.04)");bid=one(self.db,"SELECT id FROM baselines WHERE version='V2'")['id']
  with self.assertRaises(ValueError):mutate(self.db,'baseline',{'id':bid,'start':'2026-08-01','actor':'Test','reason':'Test'})
 def test_no_reason_no_override(self):
  v=self.prepare()
  with self.assertRaises(ValueError):mutate(self.db,'override',{'period':'2026-08','vehicle_id':v['id'],'source':'MANUAL','km':200,'actor':'Test','reason':''})
if __name__=='__main__':unittest.main()
