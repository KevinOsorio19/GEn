"""Exercise HTTP import/replace/retire/reload on an isolated temporary database."""
import os,sys,tempfile,threading,io,json,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl
from http.server import ThreadingHTTPServer
from backend.server import Handler

def workbook(odometer=1400,month='08'):
 w=openpyxl.Workbook();s=w.active
 s.append(['Placa','Fecha','Cantidad','Total Venta','Kilometraje','Estación','Unidad de Medida'])
 s.append(['HTTP001',f'2026-{month}-01',10,100000,1000,'EDS TEST','UGL'])
 s.append(['HTTP001',f'2026-{month}-20',12,120000,odometer,'EDS TEST','UGL'])
 out=io.BytesIO();w.save(out);return out.getvalue()
with tempfile.TemporaryDirectory() as tmp:
 os.environ['FUEL_DB']=str(Path(tmp)/'isolated.sqlite')
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 root=f'http://127.0.0.1:{server.server_port}'
 def call(path,body=None):
  if isinstance(body,dict):body=json.dumps(body).encode()
  req=urllib.request.Request(root+path,data=body,headers={'X-Fuel-App':'1'})
  try:
   response=urllib.request.urlopen(req);raw=response.read()
   return response.status,json.loads(raw) if 'application/json' in response.headers.get('Content-Type','') else raw
  except urllib.error.HTTPError as err:return err.code,json.load(err)
 try:
  upload=workbook();status,d=call('/api/import?kind=terpel&period=2026-08&name=original.xlsx',upload);assert status==200,(status,d)
  iid=d['id'];assert d['imported']==2
  assert call('/api/import?kind=terpel&period=2026-08&name=original.xlsx',upload)[1]['already_imported']
  assert call('/api/document/download?id='+str(iid))[1]==upload
  assert call('/api/document?id='+str(iid))[1]['can_retire']
  status,d=call(f'/api/document/replace?id={iid}&name=invalid.xlsx&reason=Prueba&actor=Test',workbook(month='09'));assert status==400,(status,d)
  assert call('/api/document?id='+str(iid))[1]['status']=='ACTIVO'
  status,d=call(f'/api/document/replace?id={iid}&name=corregido.xlsx&reason=Prueba&actor=Test',workbook(1600));assert status==200,(status,d)
  new=d['id'];assert call('/api/document?id='+str(iid))[1]['status']=='RETIRADO'
  status,d=call('/api/action',{'action':'process','period':'2026-08'});assert status==200,(status,d)
  assert call('/api/state?period=2026-08')[1]['results'][0]['km']==600
  status,d=call('/api/action',{'action':'retire_document','import_id':new,'reason':'Prueba','actor':'Test'});assert status==200,(status,d)
  assert call('/api/state?period=2026-08')[1]['transactions']==[]
  assert call('/api/export?period=2026-08')[0]==400
  status,d=call('/api/action',{'action':'reload_document','import_id':new,'reason':'Prueba','actor':'Test'});assert status==200,(status,d)
  assert len(call('/api/state?period=2026-08')[1]['transactions'])==2
  print('HTTP OK: carga, duplicado, descarga, reemplazo fallido/valido, retirada y recarga; base aislada.')
 finally:server.shutdown();server.server_close();thread.join()
