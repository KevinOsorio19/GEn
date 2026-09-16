import json
import unittest
import test_model
from backend.db import rows,one
from backend.importers import import_file,get_vehicle,assign
from backend.documents import retire,replace_file,reload_document,document_list
from backend.services import process,state,mutate

class DocumentTests(unittest.TestCase):
 setUp=test_model.PersistenceTests.setUp
 tearDown=test_model.PersistenceTests.tearDown
 workbook=test_model.PersistenceTests.workbook
 terpel=test_model.PersistenceTests.terpel
 prepare=test_model.PersistenceTests.prepare
 def test_retire_keeps_original_rows_and_excludes_calculation(self):
  self.prepare();iid=one(self.db,"SELECT id FROM imports WHERE kind='terpel'")['id']
  retire(self.db,iid,'Archivo incorrecto','Operador')
  self.assertEqual(len(rows(self.db,'SELECT * FROM transactions')),2)
  self.assertEqual(len(rows(self.db,'SELECT * FROM transactions WHERE active=1')),0)
  self.assertEqual(state(self.db,'2026-08')['results'],[])
  process(self.db,'2026-08');self.assertIsNone(state(self.db,'2026-08')['results'][0]['gallons'])
  self.assertEqual(document_list(self.db,'2026-08')[0]['status'],'RETIRADO')
 def test_reimport_same_file_is_new_document(self):
  r=import_file(self.db,self.terpel(),'terpel','2026-08');retire(self.db,r['id'],'Error','User')
  n=reload_document(self.db,r['id'],'Volver a usar','User')
  self.assertNotEqual(r['id'],n['id']);self.assertEqual(n['imported'],2)
  self.assertEqual(len(rows(self.db,'SELECT * FROM transactions')),4)
  self.assertEqual(len(rows(self.db,'SELECT * FROM transactions WHERE active=1')),2)
 def test_replace_corrected_odometer(self):
  self.prepare();iid=one(self.db,'SELECT id FROM imports')['id']
  p=self.terpel([['ABC123','2026-08-01 10:00:00',10,100000,1000,'EDS','UGL','1'],['ABC123','2026-08-20 10:00:00',12,120000,1600,'EDS','UGL','2']],name='corregido.xlsx')
  r=replace_file(self.db,iid,p,p.name,'Odómetro corregido','User');self.assertEqual(r['imported'],2)
  process(self.db,'2026-08');self.assertEqual(state(self.db,'2026-08')['results'][0]['km'],600)
  self.assertEqual(one(self.db,'SELECT replaces_id FROM imports WHERE id=?',(r['id'],))['replaces_id'],iid)
 def test_invalid_replacement_rolls_back_entire_operation(self):
  self.prepare();before=state(self.db,'2026-08');iid=one(self.db,'SELECT id FROM imports')['id']
  p=self.terpel([['ABC123','2026-09-01',10,100000,1000,'EDS','UGL','1']],name='incorrecto.xlsx')
  with self.assertRaises(ValueError):replace_file(self.db,iid,p,p.name,'Error','User')
  self.assertEqual(one(self.db,'SELECT status FROM imports WHERE id=?',(iid,))['status'],'ACTIVO')
  self.assertEqual(before,state(self.db,'2026-08'))
 def test_unreadable_replacement_preserves_original(self):
  r=import_file(self.db,self.terpel(),'terpel','2026-08')
  p=self.workbook([['No compatible'],['abc']],'bad.xlsx')
  with self.assertRaises(ValueError):replace_file(self.db,r['id'],p,p.name,'Error','User')
  self.assertEqual(one(self.db,'SELECT status FROM imports')['status'],'ACTIVO')
 def test_shared_duplicates_survive_other_document_retirement(self):
  a=import_file(self.db,self.terpel(),'terpel','2026-08')
  p=self.terpel(name='duplicate.xlsx')
  import openpyxl
  w=openpyxl.load_workbook(p);w.active['I1']='Otra columna';w.save(p)
  b=import_file(self.db,p,'terpel','2026-08');self.assertEqual(b['duplicates'],2)
  retire(self.db,a['id'],'Duplicado','User')
  self.assertEqual(len(rows(self.db,'SELECT id FROM transactions WHERE active=1')),2)
  retire(self.db,b['id'],'Retirar ambos','User')
  self.assertEqual(len(rows(self.db,'SELECT id FROM transactions WHERE active=1')),0)
 def test_tso_replace_and_retire(self):
  headers=['Unidad','Kms','Galones','Desde','Hasta']
  p=self.workbook([headers,['ABC123',600,12,'2026-08-01','2026-08-20']],'tso.xlsx')
  r=import_file(self.db,p,'efficiency','2026-08')
  p=self.workbook([headers,['ABC123',800,12,'2026-08-01','2026-08-20']],'newtso.xlsx')
  n=replace_file(self.db,r['id'],p,p.name,'Corrección','User')
  self.assertEqual(one(self.db,'SELECT km FROM tso WHERE active=1')['km'],800)
  self.assertEqual(len(rows(self.db,'SELECT id FROM tso')),2)
  retire(self.db,n['id'],'Retirar','User');self.assertEqual(rows(self.db,'SELECT * FROM tso WHERE active=1'),[])
 def test_prior_month_retired_does_not_supply_history(self):
  july=self.terpel([['ABC123','2026-07-31',10,100000,1000,'EDS','UGL','JUL']],'july.xlsx')
  j=import_file(self.db,july,'terpel','2026-07')
  august=self.terpel([['ABC123','2026-08-18',12,120000,1400,'EDS','UGL','AUG']],'aug.xlsx')
  import_file(self.db,august,'terpel','2026-08');process(self.db,'2026-08')
  self.assertEqual(state(self.db,'2026-08')['results'][0]['km'],400)
  retire(self.db,j['id'],'Incorrecto','User');process(self.db,'2026-08')
  self.assertIsNone(state(self.db,'2026-08')['results'][0]['km'])
 def test_closed_later_month_snapshot_unchanged(self):
  july=self.terpel([['ABC123','2026-07-31',10,100000,1000,'EDS','UGL','JUL']],'july.xlsx')
  j=import_file(self.db,july,'terpel','2026-07')
  self.prepare();mutate(self.db,'close',{'period':'2026-08'});before=state(self.db,'2026-08')
  retire(self.db,j['id'],'Retirar enero','User');self.assertEqual(before,state(self.db,'2026-08'))
 def test_closed_document_cannot_retire_replace(self):
  self.prepare();mutate(self.db,'close',{'period':'2026-08'});iid=one(self.db,'SELECT id FROM imports')['id']
  with self.assertRaises(ValueError):retire(self.db,iid,'Error','User')
  with self.assertRaises(ValueError):replace_file(self.db,iid,self.terpel(),'x.xlsx','Error','User')
 def test_master_new_files_undo_with_prior_state(self):
  p=self.workbook([['Placa','Proyecto','TIPO COMBUSTIBLE','Grupo SIPROING'],['ABC123','A','DIESEL','D3']],'master.xlsx')
  a=import_file(self.db,p,'vehicles','2026-08')
  self.assertEqual(one(self.db,'SELECT known FROM vehicles')['known'],1)
  retire(self.db,a['id'],'Carga errónea','User')
  self.assertEqual(one(self.db,'SELECT known FROM vehicles')['known'],0)
  self.assertEqual(rows(self.db,'SELECT * FROM assignments'),[])
 def test_master_later_file_requires_reverse_order(self):
  head=['Placa','Proyecto','TIPO COMBUSTIBLE','Grupo SIPROING']
  a=import_file(self.db,self.workbook([head,['ABC123','A','DIESEL','D3']],'a.xlsx'),'vehicles','2026-08')
  b=import_file(self.db,self.workbook([head,['ABC123','B','DIESEL','D3']],'b.xlsx'),'vehicles','2026-09')
  with self.assertRaises(ValueError):retire(self.db,a['id'],'Error','User')
  retire(self.db,b['id'],'Error','User');retire(self.db,a['id'],'Error','User')
  self.assertEqual(rows(self.db,'SELECT * FROM assignments'),[])
 def test_master_manual_changes_are_protected(self):
  p=self.workbook([['Placa','Proyecto'],['ABC123','A']],'master.xlsx')
  a=import_file(self.db,p,'vehicles','2026-08')
  mutate(self.db,'vehicle',{'plate':'ABC123','brand':'MANUAL','reason':'Edición posterior','actor':'User'})
  with self.assertRaises(ValueError):retire(self.db,a['id'],'Error','User')
  self.assertEqual(one(self.db,'SELECT brand FROM vehicles')['brand'],'MANUAL')
 def test_assignment_retirement_restores_previous_interval(self):
  v=get_vehicle(self.db,'ABC123');assign(self.db,v['id'],'A','2026-01-01')
  old=rows(self.db,'SELECT * FROM assignments')
  p=self.workbook([['Placa','Proyecto'],['ABC123','B']],'assign.xlsx')
  a=import_file(self.db,p,'assignments','2026-08');retire(self.db,a['id'],'Error','User')
  self.assertEqual(rows(self.db,'SELECT * FROM assignments'),old)
 def test_baseline_reimport_preserves_parameters(self):
  p=self.workbook([['GRUPO','M (Pendiente)','B (intercepto)','V','META DE AHORRO %'],['D3',.03,2,'V1',.05]],'lb.xlsx')
  a=import_file(self.db,p,'baseline','2026-08');retire(self.db,a['id'],'Error','User')
  self.assertEqual(one(self.db,'SELECT active FROM baselines')['active'],0)
  b=reload_document(self.db,a['id'],'Recuperar','User');self.assertEqual(b['duplicates'],1)
  self.assertEqual(one(self.db,'SELECT active FROM baselines')['active'],1)
  self.assertEqual(len(rows(self.db,'SELECT * FROM baselines')),1)
 def test_retire_suspends_source_overrides(self):
  v=self.prepare();mutate(self.db,'override',{'period':'2026-08','vehicle_id':v['id'],'source':'MANUAL','km':500,'reason':'Soporte','actor':'User'})
  iid=one(self.db,'SELECT id FROM imports')['id'];retire(self.db,iid,'Error','User')
  self.assertEqual(one(self.db,"SELECT active FROM overrides WHERE entity='result'")['active'],0)
 def test_retire_requires_actor_and_reason(self):
  r=import_file(self.db,self.terpel(),'terpel','2026-08')
  with self.assertRaises(ValueError):retire(self.db,r['id'],'','User')
  self.assertEqual(one(self.db,'SELECT status FROM imports')['status'],'ACTIVO')

 def test_monthly_document_view_hides_permanent_sources(self):
  monthly=self.terpel(); import_file(self.db,monthly,'terpel','2026-08')
  fleet=self.workbook([['Placa'],['ABC123']],'fleet.xlsx'); import_file(self.db,fleet,'vehicles','2026-08')
  lb=self.workbook([['GRUPO','M (Pendiente)','B (intercepto)','V'],['D3',.03,2,'V1']],'lb.xlsx'); import_file(self.db,lb,'baseline','2026-08')
  docs=document_list(self.db,'2026-08')
  self.assertEqual([d['kind'] for d in docs],['terpel'])

 def test_all_four_monthly_documents_can_be_retired(self):
  p=self.terpel(); import_file(self.db,p,'terpel','2026-08')
  for kind,headers,row in [('assignments',['Placa','CC'],['ABC123',586]),('summary',['Unidad','Distancia Recorrida'],['ABC123',100]),('efficiency',['Unidad','Kms','Galones','Desde','Hasta'],['ABC123',100,10,'2026-08-01','2026-08-02'])]:
   import_file(self.db,self.workbook([headers,row],kind+'.xlsx'),kind,'2026-08')
  docs=document_list(self.db,'2026-08');self.assertEqual(len(docs),4);self.assertTrue(all(d['can_retire'] for d in docs))
