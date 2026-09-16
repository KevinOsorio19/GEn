import unittest
import test_model
from backend.importers import import_file
from backend.db import rows,one
class MonthlySourceTests(unittest.TestCase):
 setUp=test_model.PersistenceTests.setUp
 tearDown=test_model.PersistenceTests.tearDown
 workbook=test_model.PersistenceTests.workbook
 def test_master_without_project(self):
  p=self.workbook([['Placa','Marca'],['AAA123','Marca']])
  self.assertEqual(import_file(self.db,p,'vehicles','2026-01')['imported'],1)
  self.assertEqual(rows(self.db,'SELECT * FROM assignments'),[])
  self.assertEqual(rows(self.db,'SELECT * FROM periods'),[])
 def test_master_project_column_does_not_assign(self):
  p=self.workbook([['Placa','Proyecto'],['AAA123','999']])
  import_file(self.db,p,'vehicles','2026-01')
  self.assertEqual(rows(self.db,'SELECT * FROM assignments'),[])
 def test_monthly_two_columns_preserve_master(self):
  p=self.workbook([['Placa','Marca','Grupo SIPROING'],['AAA123','Marca','D3']],'master.xlsx')
  import_file(self.db,p,'vehicles','2026-01')
  for month,project in [('01','A'),('02','B')]:
   p=self.workbook([['Placa','Proyecto'],['AAA123',project]],month+'.xlsx')
   import_file(self.db,p,'assignments','2026-'+month)
  a=rows(self.db,'SELECT * FROM assignments ORDER BY start')
  self.assertEqual(a[0]['end'],'2026-01-31');self.assertEqual(a[1]['start'],'2026-02-01')
  self.assertEqual(one(self.db,'SELECT brand FROM vehicles')['brand'],'Marca')

 def test_monthly_group_is_only_a_period_override(self):
  p=self.workbook([['Placa','Marca','Grupo SIPROING'],['AAA123','Marca','D3']],'master.xlsx')
  import_file(self.db,p,'vehicles','2026-01')
  p=self.workbook([['Placa','CC','Grupo'],['AAA123',586,'G2']],'novelty.xlsx')
  import_file(self.db,p,'assignments','2026-01')
  self.assertEqual(one(self.db,'SELECT energy_group FROM vehicles')['energy_group'],'D3')
  self.assertEqual(one(self.db,"SELECT value FROM overrides WHERE entity='period_group'")['value'],'G2')
 def test_permanent_file_deduplicated_across_months(self):
  p=self.workbook([['Placa'],['AAA123']])
  import_file(self.db,p,'vehicles','2026-01')
  self.assertTrue(import_file(self.db,p,'vehicles','2026-02')['already_imported'])
 def test_exact_twelve_columns_from_screenshot(self):
  from backend.fleet import enrich
  headers=['Placa','Tipo Vehículo','Tipo Placa','Modelo','Marca','Línea Vehículo','Proyecto','Propietario','Tipo Propiedad','Estado','TIPO COMBUSTIBLE','CILINDRAJE']
  values=['MI021991','MONTACARGAS','SIN PLACAS',2013,'CATERPILLAR','GP25NM',1,'PROING S.A','PROPIO','ACTIVO','GASGASOL',100]
  p=self.workbook([headers,values]);r=import_file(self.db,p,'vehicles','2026-01')
  self.assertEqual(r['imported'],1);self.assertEqual(r['warnings'],0)
  v=enrich(one(self.db,'SELECT * FROM vehicles'))
  self.assertEqual(v['plate_type'],'SIN PLACAS');self.assertEqual(v['line'],'GP25NM')
  self.assertEqual(v['owner'],'PROING S.A');self.assertEqual(v['ownership_type'],'PROPIO')
  self.assertEqual(v['reference_project'],1);self.assertEqual(v['displacement'],100)
  self.assertIsNone(v['energy_group']);self.assertEqual(rows(self.db,'SELECT * FROM assignments'),[])
 def test_unaccented_headers(self):
  p=self.workbook([['Placa','Tipo Vehiculo','Linea Vehiculo'],['ABC123','CAMIONETA','HILUX']])
  import_file(self.db,p,'vehicles','2026-01')
  from backend.fleet import enrich
  v=enrich(one(self.db,'SELECT * FROM vehicles'));self.assertEqual(v['type'],'CAMIONETA');self.assertEqual(v['line'],'HILUX')
