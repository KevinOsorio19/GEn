from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from pathlib import Path
import json,io,tempfile,traceback,os
from http.cookies import SimpleCookie
from . import accounts
import openpyxl
from .db import connect,ROOT,rows
from .services import state,mutate,vehicle_detail,result_list
from .importers import import_file,dump
from .documents import document_list,detail,replace_file
from .fleet import enrich
class Handler(BaseHTTPRequestHandler):
 def log_message(self,format,*args):
  # Invitation tokens are sent in fragments/POST bodies, never access logs.
  super().log_message(format,*args)
 def session_token(self):
  cookie=SimpleCookie()
  try:cookie.load(self.headers.get('Cookie',''))
  except Exception:return ''
  return cookie['fuel_session'].value if 'fuel_session' in cookie else ''
 def account(self):return accounts.session_user(self.session_token()) if accounts.enabled() else None
 def workspace(self):
  self.current_user=self.account()
  if accounts.enabled():
   if not self.current_user:
    self.send(401,{'error':'Inicie sesión para acceder a su perfil'});return None
   return connect(accounts.workspace_path(self.current_user['workspace']))
  return connect()
 def set_session(self,token):
  secure='; Secure' if os.environ.get('FUEL_PUBLIC_URL','').startswith('https://') else ''
  self.response_cookie='fuel_session='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age='+str(accounts.SESSION_SECONDS if token else 0)+secure
 def send(self,status,body,content_type='application/json; charset=utf-8',filename=None):
  if isinstance(body,(dict,list)):body=dump(body).encode()
  elif isinstance(body,str):body=body.encode()
  self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
  if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
  self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
  if getattr(self,'response_cookie',None):self.send_header('Set-Cookie',self.response_cookie)
  self.end_headers();self.wfile.write(body)
 def do_GET(self):
  q=parse_qs(urlparse(self.path).query);path=urlparse(self.path).path;p=q.get('period',['2026-08'])[0]
  if path=='/health':return self.send(200,{'status':'ok'})
  if path=='/api/auth/me':return self.send(200,{'enabled':accounts.enabled(),'user':accounts.user_summary(self.account()) if self.account() else None})
  if not path.startswith('/api/'):
   if path=='/' and accounts.enabled() and not self.account():path='/login.html'
   filename='index.html' if path=='/' else path.lstrip('/')
   target=(ROOT/'web'/filename).resolve()
   if not target.is_relative_to(ROOT/'web') or not target.is_file():return self.send(404,'No encontrado','text/plain')
   import mimetypes
   return self.send(200,target.read_bytes(),mimetypes.guess_type(target)[0] or 'application/octet-stream')
  db=self.workspace()
  if db is None:return
  try:
   if path=='/api/documents':return self.send(200,document_list(db,p))
   if path=='/api/document':return self.send(200,detail(db,int(q['id'][0])))
   if path=='/api/document/download':
    from .db import one
    d=one(db,'SELECT path FROM imports WHERE id=?',(int(q['id'][0]),))
    if not d or not Path(d['path']).is_file():raise ValueError('No se encuentra la copia original de este documento')
    return self.send(200,Path(d['path']).read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','documento-'+q['id'][0]+'.xlsx')
   if path=='/api/state':return self.send(200,state(db,p))
   if path=='/api/catalog':
    return self.send(200,{'vehicles':[enrich(v) for v in rows(db,"SELECT v.*,COALESCE((SELECT p.name FROM assignments a JOIN projects p ON p.id=a.project_id WHERE a.vehicle_id=v.id AND a.end IS NULL ORDER BY a.start DESC LIMIT 1),'Sin asignar') project FROM vehicles v ORDER BY plate")],'projects':rows(db,'SELECT * FROM projects ORDER BY code'),'baselines':rows(db,'SELECT * FROM baselines WHERE active=1 ORDER BY energy_group,version'),'settings':{r['key']:r['value'] for r in rows(db,'SELECT * FROM settings')}})
   if path=='/api/vehicle':return self.send(200,vehicle_detail(db,int(q['id'][0])))
   if path=='/api/history':
    return self.send(200,[{'period':r['period'],'status':r['status'],'demo':r['demo'],'results':result_list(db,r['period'])} for r in rows(db,'SELECT * FROM periods ORDER BY period')])
   if path=='/api/export':
    if state(db,p)['period']['status']=='BORRADOR':raise ValueError('Procese el período actualizado antes de exportar resultados')
    data=state(db,p)['results'];project=q.get('project',[''])[0];search=q.get('search',[''])[0].upper()
    data=[r for r in data if (not project or r['project']==project) and (not search or search in r['plate'])]
    for query,key in [('fuel','fuel'),('group','energy_group'),('quality','quality'),('compliance','compliance')]:
     value=q.get(query,[''])[0]
     if value:data=[r for r in data if r.get(key)==value]
    if q.get('view',[''])[0]=='deviations':
     ids=q.get('ids',[''])[0].split(',')
     by_id={str(r['vehicle_id']):r for r in data if r.get('ic') is not None}
     data=[by_id[i] for i in dict.fromkeys(ids) if i in by_id][:8]
    w=openpyxl.Workbook();s=w.active;s.title='Resultados'
    keys=['plate','project','energy_group','fuel','km','source','gallons','theoretical','ic','target','compliance','quality','operational_status','notes']
    s.append(['Placa','Proyecto','Grupo','Combustible','Km','Fuente km','Galones consumidos','Galones teóricos','IC','Meta','Cumplimiento','Calidad','Estado período','Observación'])
    for r in data:
     r={**r,'notes':' · '.join(r.get('notes') or [])}
     # Avoid Excel formula injection from user-provided identifiers.
     s.append([("'"+r[k] if isinstance(r.get(k),str) and r[k].startswith(('=','+','-','@')) else r.get(k)) for k in keys])
    s.freeze_panes='A2';s.auto_filter.ref=s.dimensions
    from openpyxl.styles import Font,PatternFill
    for c in s[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='123B55')
    for col in s.columns:s.column_dimensions[col[0].column_letter].width=24
    for row in s.iter_rows(min_row=2):
     for c in row[8:10]:c.number_format='0.00%'
    f=io.BytesIO();w.save(f)
    return self.send(200,f.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','resultados-'+p+'.xlsx')
   if path.startswith('/api/'):return self.send(404,{'error':'Ruta no encontrada'})
   filename='index.html' if path=='/' else path.lstrip('/')
   target=(ROOT/'web'/filename).resolve()
   if not target.is_relative_to(ROOT/'web') or not target.is_file():return self.send(404,'No encontrado','text/plain')
   import mimetypes
   return self.send(200,target.read_bytes(),mimetypes.guess_type(target)[0] or 'application/octet-stream')
  except (ValueError,KeyError) as e:self.send(400,{'error':str(e)})
  except Exception:traceback.print_exc();self.send(500,{'error':'No se pudo completar la consulta. Revise el registro del servidor.'})
  finally:db.close()
 def do_POST(self):
  # This local MVP never accepts cross-origin mutations or remote uploads.
  host=self.headers.get('Host','');origin=self.headers.get('Origin')
  allowed=[os.environ['FUEL_PUBLIC_URL'].rstrip('/')] if os.environ.get('FUEL_PUBLIC_URL') else ['http://'+host,'https://'+host]
  if origin and origin not in allowed:return self.send(403,{'error':'Origen no autorizado'})
  if self.headers.get('X-Fuel-App')!='1':return self.send(403,{'error':'Solicitud no autorizada'})
  try:length=int(self.headers.get('Content-Length','0'))
  except ValueError:return self.send(400,{'error':'Tamaño inválido'})
  if length<0:return self.send(400,{'error':'Tamaño inválido'})
  if length>20*1024*1024:return self.send(413,{'error':'Máximo 20 MB por archivo'})
  path=urlparse(self.path).path
  if path.startswith('/api/auth/'):
   if not accounts.enabled():return self.send(404,{'error':'Cuentas no habilitadas'})
   if length>16384:return self.send(400,{'error':'Solicitud demasiado grande'})
   try:
    data=json.loads(self.rfile.read(length));user=self.account()
    if path=='/api/auth/login':
     token=accounts.login(data.get('username'),data.get('password'),self.client_address[0]);self.set_session(token)
     return self.send(200,{'ok':True})
    if path=='/api/auth/accept':
     token=accounts.accept_invitation(data.get('token'),data.get('username'),data.get('password'));self.set_session(token)
     return self.send(200,{'ok':True})
    if not user:return self.send(401,{'error':'Inicie sesión'})
    if path=='/api/auth/logout':
     accounts.logout(self.session_token());self.set_session('');return self.send(200,{'ok':True})
    if path=='/api/auth/password':
     accounts.change_password(user,data.get('password'),data.get('new_password'));self.set_session('');return self.send(200,{'ok':True})
    if path=='/api/auth/invite':
     token=accounts.create_invitation(None,data.get('name'),actor=user['id'])
     return self.send(200,{'invitation':'/login.html#invite='+token,'expires_hours':48})
    return self.send(404,{'error':'Ruta no encontrada'})
   except PermissionError as err:return self.send(403,{'error':str(err)})
   except (ValueError,TypeError,KeyError):return self.send(400,{'error':str(__import__('sys').exc_info()[1])})
   except Exception:
    traceback.print_exc();return self.send(500,{'error':'No se pudo completar la operación de la cuenta'})
  db=self.workspace()
  if db is None:return
  try:
   q=parse_qs(urlparse(self.path).query);path=urlparse(self.path).path;body=self.rfile.read(length)
   if path in ['/api/import','/api/document/replace']:
    name=q.get('name',['archivo.xlsx'])[0]
    if not name.lower().endswith('.xlsx'):raise ValueError('Solo se admite .xlsx')
    with tempfile.NamedTemporaryFile(suffix='.xlsx') as f:
     f.write(body);f.flush()
     with db:
      db.execute('BEGIN IMMEDIATE')
      if path=='/api/document/replace':result=replace_file(db,int(q['id'][0]),f.name,Path(name).name,q.get('reason',[''])[0],self.current_user['username'] if self.current_user else q.get('actor',[''])[0])
      else:result=import_file(db,f.name,q['kind'][0],q['period'][0],original_name=Path(name).name)
   elif path=='/api/action':
    data=json.loads(body)
    if self.current_user:data['actor']=self.current_user['username']
    with db:
     db.execute('BEGIN IMMEDIATE')
     result=mutate(db,data.pop('action'),data)
   else:return self.send(404,{'error':'Acción no encontrada'})
   self.send(200,result)
  except (ValueError,KeyError,TypeError) as e:db.rollback();self.send(400,{'error':str(e)})
  except Exception as e:
   db.rollback()
   import sqlite3,zipfile
   if isinstance(e,(sqlite3.IntegrityError,zipfile.BadZipFile)):self.send(400,{'error':'Archivo inválido o registro duplicado incompatible: '+str(e)})
   else:traceback.print_exc();self.send(500,{'error':'No se pudo completar la operación. No se incorporaron cambios parciales.'})
  finally:db.close()
if __name__=='__main__':
 port=int(os.environ.get('PORT','8765'))
 host=os.environ.get('FUEL_BIND','127.0.0.1')
 if host not in ['127.0.0.1','localhost'] and (not accounts.enabled() or not os.environ.get('FUEL_PUBLIC_URL','').startswith('https://')):
  raise SystemExit('El acceso externo requiere cuentas habilitadas y FUEL_PUBLIC_URL con HTTPS detrás de un proxy TLS')
 print(f'Gestión de combustible: {os.environ.get("FUEL_PUBLIC_URL") or f"http://{host}:{port}"}',flush=True)
 ThreadingHTTPServer((host,port),Handler).serve_forever()
