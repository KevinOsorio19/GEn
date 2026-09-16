import hashlib,json,re,calendar
from datetime import datetime,date
from pathlib import Path
import openpyxl
from .db import ROOT,one,rows
from .documents import link,journal,master_state,invalidate

def dump(v):return json.dumps(v,ensure_ascii=False,default=str,allow_nan=False)
def norm(v):return re.sub(r'\s+',' ',str(v or '').strip()).upper()
def version_key(v):
 s=norm(v).replace('VERSIÓN','V').replace('VERSION','V').replace(' ','')
 m=re.fullmatch(r'V(?:ER)?(?:SION)?([0-9]+)',s)
 return ('V'+m.group(1)) if m else s
def plate(v):return re.sub(r'[\s-]+','',norm(v))
def numeric(v):
 if v is None or isinstance(v,bool):return None
 if isinstance(v,(int,float)):
  import math
  return float(v) if math.isfinite(v) else None
 s=str(v).strip().replace('%','')
 if ',' in s:s=s.replace('.','').replace(',','.')
 try:
  n=float(s)
  import math
  return n if math.isfinite(n) else None
 except ValueError:return None

def timestamp(v):
 if isinstance(v,datetime):return v.isoformat(sep=' ',timespec='seconds')
 if isinstance(v,date):return str(v)+' 00:00:00'
 s=str(v or '').strip()
 for f in ['%Y-%m-%d %H:%M:%S','%Y-%m-%d','%d/%m/%Y %H:%M:%S','%d/%m/%Y']:
  try:return datetime.strptime(s,f).isoformat(sep=' ',timespec='seconds')
  except ValueError:pass
 raise ValueError('Fecha inválida: '+s)
def period_check(p):
 if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',p):raise ValueError('Período inválido; use AAAA-MM')
def ensure_open(db,p):
 period_check(p)
 if one(db,'SELECT period FROM periods WHERE period=? AND status="CERRADO"',(p,)):raise ValueError('El período está cerrado y sus resultados son inmutables')
 db.execute('INSERT OR IGNORE INTO periods(period) VALUES (?)',(p,))
def get_vehicle(db,p,known=False):
 p=plate(p)
 if not p:raise ValueError('Placa vacía')
 r=one(db,'SELECT * FROM vehicles WHERE plate=?',(p,))
 if r:return r
 db.execute('INSERT INTO vehicles(plate,known,status) VALUES (?,?,?)',(p,int(known),'ACTIVO' if known else 'DESCONOCIDO'))
 return one(db,'SELECT * FROM vehicles WHERE plate=?',(p,))
def assign(db,vid,code,start,assumption='Fecha de carga mensual; no equivale a fecha corporativa exacta'):
 code=str(code).strip()
 if not code:return
 db.execute('INSERT OR IGNORE INTO projects(code,name) VALUES (?,?)',(code,'Proyecto '+code))
 project=one(db,'SELECT * FROM projects WHERE code=?',(code,))
 current=one(db,'SELECT * FROM assignments WHERE vehicle_id=? AND start<=? AND (end IS NULL OR end>=?) ORDER BY start DESC',(vid,start,start))
 if current and current['project_id']==project['id']:return
 if current and current['start']==start:raise ValueError('Asignación distinta con la misma fecha; requiere revisión')
 if current:
  from datetime import timedelta
  end=(date.fromisoformat(start)-timedelta(days=1)).isoformat()
  db.execute('UPDATE assignments SET end=? WHERE id=?',(end,current['id']))
 future=one(db,'SELECT * FROM assignments WHERE vehicle_id=? AND start>? ORDER BY start LIMIT 1',(vid,start))
 end=None
 if future:
  from datetime import timedelta
  end=(date.fromisoformat(future['start'])-timedelta(days=1)).isoformat()
 db.execute('INSERT INTO assignments(vehicle_id,project_id,start,end,assumption) VALUES (?,?,?,?,?)',(vid,project['id'],start,end,assumption))

def extract(path,kind):
 w=openpyxl.load_workbook(path,read_only=True,data_only=True)
 required={'vehicles':['PLACA'],'assignments':['PLACA'],'terpel':['PLACA','FECHA','CANTIDAD','TOTAL VENTA','KILOMETRAJE'],'summary':['UNIDAD','DISTANCIA RECORRIDA'],'efficiency':['UNIDAD','KMS','GALONES','DESDE','HASTA'],'baseline':['GRUPO','M (PENDIENTE)','B (INTERCEPTO)','V']}
 if kind not in required:raise ValueError('Tipo de importación desconocido')
 for sheet in w:
  values=list(sheet.values)
  for i,r in enumerate(values[:100]):
   headers=[{'TIPO VEHICULO':'TIPO VEHÍCULO','LINEA VEHICULO':'LÍNEA VEHÍCULO','LÍNEA VEHICULO':'LÍNEA VEHÍCULO','LINEA VEHÍCULO':'LÍNEA VEHÍCULO'}.get(norm(c),norm(c)) for c in r]
   if all(c in headers for c in required[kind]):
    records=[(j+1,{headers[k]:v for k,v in enumerate(row) if k<len(headers) and headers[k]}) for j,row in enumerate(values[i+1:],i+1) if any(v is not None and str(v).strip() for v in row)]
    return sheet.title,i+1,records,values[:i]
 raise ValueError('No se encontró una hoja con las columnas mínimas: '+', '.join(required[kind]))

def import_file(db,path,kind,period,demo=False,original_name=None):
 period_check(period)
 if kind not in ['vehicles','baseline']:ensure_open(db,period)
 path=Path(path)
 if path.suffix.lower()!='.xlsx':raise ValueError('Solo se admiten archivos .xlsx')
 if path.stat().st_size>20*1024*1024:raise ValueError('El límite por archivo es 20 MB')
 import zipfile
 with zipfile.ZipFile(path) as z:
  if sum(i.file_size for i in z.infolist())>100*1024*1024:raise ValueError('El contenido descomprimido supera 100 MB')
 if kind=='terpel':
  mode=one(db,'SELECT demo FROM periods WHERE period=?',(period,))['demo']
  if bool(mode)!=bool(demo):raise ValueError('No mezcle Terpel real y de prueba en el mismo período. Use una base separada para producción.')
 content=path.read_bytes();digest=hashlib.sha256(content).hexdigest()
 old=one(db,"SELECT * FROM imports WHERE kind=? AND period=? AND hash=? AND demo=? AND status='ACTIVO'",(kind,period,digest,int(demo)))
 if kind in ['vehicles','baseline']:
  old=one(db,"SELECT * FROM imports WHERE kind=? AND hash=? AND demo=? AND status='ACTIVO' ORDER BY id DESC LIMIT 1",(kind,digest,int(demo)))
 if old:return {**json.loads(old['report']),'already_imported':True,'message':'Este archivo ya fue importado'}
 sheet,header,records,preamble=extract(path,kind)
 if kind=='summary':
  dates=[str(v)[:7] for row in preamble for v in row if re.match(r'^\d{4}-\d{2}-\d{2}',str(v))]
  if dates and any(d!=period for d in dates):raise ValueError('TSO sumarizado corresponde a '+', '.join(sorted(set(dates)))+'; seleccione ese período')
 database_path=db.execute('PRAGMA database_list').fetchone()[2]
 folder=Path(database_path).parent/'originals';folder.mkdir(parents=True,exist_ok=True)
 saved=folder/(digest+'.xlsx')
 if not saved.exists():saved.write_bytes(content)
 cur=db.execute('INSERT INTO imports(kind,period,name,hash,path,demo) VALUES (?,?,?,?,?,?)',(kind,period,original_name or path.name,digest,str(saved),int(demo)))
 iid=cur.lastrowid
 db.execute('UPDATE imports SET managed=1 WHERE id=?',(iid,))
 report=dict(id=iid,kind=kind,sheet=sheet,header_row=header,imported=0,duplicates=0,warnings=0,unknown=0,errors=[],periods=[],demo=bool(demo))
 seen=set();detected=set()
 for rownum,r in records:
  db.execute('SAVEPOINT import_row')
  try:
   if kind=='baseline':
    group=norm(r['GRUPO']);version=version_key(r['V']);version_label=str(r['V'] or '').strip();sample_n=numeric(r.get('N'));slope=numeric(r['M (PENDIENTE)']);intercept=numeric(r['B (INTERCEPTO)']);z_value=numeric(r.get('Z'));sy_value=numeric(r.get('SY'));target=numeric(r.get('META DE AHORRO %'));potential=numeric(r.get('POTENCIAL DE AHORRO %'))
    if not group or not version:raise ValueError('Grupo o versión vacíos')
    prior=one(db,'SELECT * FROM baselines WHERE energy_group=? AND version=?',(group,version))
    if prior:
     if any(prior[k]!=v for k,v in [('slope',slope),('intercept',intercept),('target',target),('potential',potential)]):raise ValueError('La versión ya existe con valores distintos; cree una nueva versión')
     link(db,iid,'baselines',prior['id'])
     db.execute('UPDATE baselines SET active=1 WHERE id=?',(prior['id'],))
     report['duplicates']+=1;continue
    db.execute('INSERT INTO baselines(energy_group,version,version_label,sample_n,slope,intercept,z_value,sy_value,target,potential,import_id,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(group,version,version_label,sample_n,slope,intercept,z_value,sy_value,target,potential,iid,dump(r)))
    link(db,iid,'baselines',db.execute('SELECT last_insert_rowid()').fetchone()[0])
    if slope is None or intercept is None or target is None:report['warnings']+=1
   elif kind in ['vehicles','assignments']:
    v=get_vehicle(db,r['PLACA'])
    before=master_state(db,v['id'])
    if kind=='vehicles':
     group_value=norm(r.get('GRUPO SIPROING') or r.get('GRUPO')) or v['source_group']
     db.execute('UPDATE vehicles SET type=?,model=?,brand=?,fuel=?,displacement=?,source_group=?,energy_group=?,status=?,known=1,raw=?,import_id=? WHERE id=?',(r.get('TIPO VEHÍCULO'),str(r.get('MODELO','')),r.get('MARCA'),norm(r.get('TIPO COMBUSTIBLE')),numeric(r.get('CILINDRAJE')),group_value,group_value,norm(r.get('ESTADO')) or 'ACTIVO',dump(r),iid,v['id']))
    if kind=='assignments':
     project_value=r.get('PROYECTO') if r.get('PROYECTO') is not None else r.get('CC')
     if project_value is None or not str(project_value).strip():raise ValueError('Proyecto/CC vacío')
     start=period+'-01'
     assign(db,v['id'],project_value,start)
     monthly_group = r.get('GRUPO') or r.get('GRUPO ENERGÉTICO') or r.get('GRUPO SIPROING')
     if monthly_group is not None and str(monthly_group).strip():
      db.execute("INSERT INTO overrides(period,vehicle_id,entity,field,original,value,reason,actor) VALUES (?,?,?,?,?,?,?,?)",(period,v['id'],'period_group','energy_group',v.get('energy_group'),norm(monthly_group),'Novedad indicada en archivo mensual','Carga mensual'))
     monthly_status = r.get('ESTADO') or r.get('STATUS')
     if monthly_status is not None and str(monthly_status).strip():
      db.execute("INSERT INTO overrides(period,vehicle_id,entity,field,original,value,reason,actor) VALUES (?,?,?,?,?,?,?,?)",(period,v['id'],'period_status','status',v.get('status'),norm(monthly_status),'Estado operativo indicado en archivo mensual','Carga mensual'))
     if not v['known']:
      report['unknown']+=1
      db.execute('INSERT INTO issues(import_id,period,vehicle_id,row_number,reason,raw) VALUES (?,?,?,?,?,?)',(iid,period,v['id'],rownum,'Placa desconocida en flota PROING: '+v['plate'],dump(r)))
    journal(db,iid,v['id'],before,master_state(db,v['id']))
   elif kind=='terpel':
    d=timestamp(r['FECHA']);detected.add(d[:7])
    if d[:7]!=period:raise ValueError('Fecha fuera del período seleccionado: '+d[:10]+'. Cargue en '+d[:7])
    q=numeric(r['CANTIDAD']);cost=numeric(r['TOTAL VENTA']);odometer=numeric(r['KILOMETRAJE'])
    if q is None or q<=0 or cost is None or cost<0:raise ValueError('Cantidad o valor inválidos')
    if norm(r.get('UNIDAD DE MEDIDA')) not in ['UGL','GAL','GALONES']:raise ValueError('Unidad no reconocida como galones')
    v=get_vehicle(db,r['PLACA'])
    station=norm(r.get('ESTACIÓN'));original_id=str(r.get('IDENTIFICADOR DE LA VENTA') or r.get('NO VENTA') or '')
    identity=[v['plate'],d,station,norm(r.get('PRODUCTO')),q,cost,int(demo)]
    fp=hashlib.sha256(dump(identity).encode()).hexdigest()
    existing=one(db,'SELECT id,odometer FROM transactions WHERE fingerprint=? AND active=1',(fp,))
    if existing:
     if existing['odometer']!=odometer:raise ValueError('La misma venta tiene un odómetro diferente; use Reemplazar documento')
     link(db,iid,'transactions',existing['id'])
     report['duplicates']+=1;continue
    # Same issuer/station sale ID with conflicting content is quarantined.
    if original_id and one(db,'SELECT id FROM transactions WHERE original_id=? AND station=? AND demo=? AND active=1',(original_id,station,int(demo))):raise ValueError('Identificador de venta existente con datos diferentes')
    db.execute('INSERT INTO transactions(vehicle_id,date,station,city,fuel,gallons,cost,odometer,original_id,fingerprint,import_id,row_number,raw,flags,demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(v['id'],d,station,r.get('REGIONAL'),norm(r.get('PRODUCTO')),q,cost,odometer,original_id,fp,iid,rownum,dump(r),dump(['Odómetro inválido'] if odometer is None or odometer<=0 else []),int(demo)))
    link(db,iid,'transactions',db.execute('SELECT last_insert_rowid()').fetchone()[0])
    if not v['known']:
     report['unknown']+=1
     db.execute('INSERT INTO issues(import_id,period,vehicle_id,row_number,reason,raw) VALUES (?,?,?,?,?,?)',(iid,period,v['id'],rownum,'Placa desconocida: '+v['plate'],dump(r)))
   else:
    if not r.get('UNIDAD'):continue
    v=get_vehicle(db,r['UNIDAD'])
    if kind=='efficiency':
     start=timestamp(r['DESDE']);end=timestamp(r['HASTA']);detected.update([start[:7],end[:7]])
     if start[:7]!=period or end[:7]!=period or end<start:raise ValueError('Intervalo TSO fuera del período o invertido')
     values=(numeric(r['KMS']),numeric(r['GALONES']),numeric(r.get('KM/GAL')),numeric(r.get('COSTO')),start,end,None,None,None)
    else:values=(numeric(r.get('DISTANCIA RECORRIDA')),None,None,None,period+'-01',period+'-'+str(calendar.monthrange(int(period[:4]),int(period[5:]))[1]),numeric(r.get('HORA DE VIAJE')),numeric(r.get('HORA DE RALENTÍ')),numeric(r.get('HORA ENCEND.')))
    if values[0] is None or values[0]<0:raise ValueError('Kilómetros TSO inválidos')
    existing=one(db,'SELECT id,raw FROM tso WHERE vehicle_id=? AND period=? AND kind=? AND active=1',(v['id'],period,kind))
    if existing:
     if existing['raw']==dump(r):
      link(db,iid,'tso',existing['id'])
      report['duplicates']+=1;continue
     raise ValueError('TSO ya existe con datos diferentes; requiere revisión antes de sustituir')
    db.execute('INSERT INTO tso(vehicle_id,period,kind,km,gallons,efficiency,cost,start,end,drive_hours,idle_hours,engine_hours,import_id,row_number,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(v['id'],period,kind,*values,iid,rownum,dump(r)))
    link(db,iid,'tso',db.execute('SELECT last_insert_rowid()').fetchone()[0])
    if not v['known']:
     report['unknown']+=1
     db.execute('INSERT INTO issues(import_id,period,vehicle_id,row_number,reason,raw) VALUES (?,?,?,?,?,?)',(iid,period,v['id'],rownum,'Placa TSO desconocida: '+v['plate'],dump(r)))
   report['imported']+=1
  except (ValueError,KeyError,TypeError) as e:
   db.execute('ROLLBACK TO import_row')
   report['warnings']+=1;report['errors'].append({'row':rownum,'reason':str(e)})
   db.execute('INSERT INTO issues(import_id,period,row_number,reason,raw) VALUES (?,?,?,?,?)',(iid,period,rownum,str(e),dump(r)))
  finally:db.execute('RELEASE import_row')
 report['periods']=sorted(detected) or [period]
 report['warnings']+=report['unknown']
 db.execute('UPDATE imports SET report=? WHERE id=?',(dump(report),iid))
 # Recalculation must be explicit after any import.
 invalidate(db)
 db.execute('INSERT INTO document_events(import_id,event,actor,reason,data) VALUES (?,?,?,?,?)',(iid,'IMPORTADO','Carga de archivo','Archivo incorporado',dump(report)))
 return report
