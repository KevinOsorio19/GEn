import json,calendar,math
from datetime import datetime,date
from .db import one,rows
from .importers import ensure_open,period_check,dump,assign,get_vehicle,numeric
from .engine import calculate
from .fleet import enrich,FIELDS
from .documents import retire,document_list,reload_document

def audit(db,entity,field,original,value,reason,actor,period=None,vid=None,before=None,after=None):
 if not str(reason or '').strip() or not str(actor or '').strip():raise ValueError('Indique motivo y responsable de la corrección')
 cur=db.execute('INSERT INTO overrides(period,vehicle_id,entity,field,original,value,reason,actor,before_result,after_result) VALUES (?,?,?,?,?,?,?,?,?,?)',(period,vid,entity,field,dump(original),dump(value),reason,actor,dump(before),dump(after)))
 return cur.lastrowid

def validate_tank_limit(value):
 if value is None or value=='':return
 limit=numeric(value)
 if limit is None or not math.isfinite(limit) or limit<=0:raise ValueError('El máximo por tanqueada debe ser mayor que cero; déjelo vacío si no está definido')

def check_baseline_overlap(db,b,start,end):
 conflict=one(db,'SELECT * FROM baselines WHERE active=1 AND id<>? AND energy_group=? AND status="ACTIVA" AND start<=? AND (end IS NULL OR end>=?)',(b['id'],b['energy_group'],end or '9999-12-31',start))
 if conflict:raise ValueError(f"Cruce de vigencias: grupo {b['energy_group']}, versión {conflict['version']} ({conflict['start']} a {conflict['end'] or 'sin fecha final'}). No pueden existir dos líneas activas del mismo grupo en esas fechas.")

def process(db,period):
 ensure_open(db,period)
 end=period+'-'+str(calendar.monthrange(int(period[:4]),int(period[5:]))[1])
 state=one(db,'SELECT * FROM periods WHERE period=?',(period,))
 candidates=rows(db,'''SELECT DISTINCT v.* FROM vehicles v WHERE
 (v.status NOT IN ('RETIRADO','VENDIDO','PERDIDA TOTAL') AND EXISTS(SELECT 1 FROM assignments a WHERE a.vehicle_id=v.id AND a.start<=? AND (a.end IS NULL OR a.end>=?)))
 OR EXISTS(SELECT 1 FROM transactions t WHERE t.active=1 AND t.vehicle_id=v.id AND substr(t.date,1,7)=? AND t.demo=?)
 OR EXISTS(SELECT 1 FROM tso t WHERE t.active=1 AND t.vehicle_id=v.id AND t.period=?)''',(end,period+'-01',period,state['demo'],period))
 settings={r['key']:float(r['value']) for r in rows(db,'SELECT * FROM settings')}
 db.execute('DELETE FROM results WHERE period=?',(period,))
 for v in candidates:
  tanks=rows(db,'SELECT * FROM transactions WHERE active=1 AND vehicle_id=? AND substr(date,1,7)=? AND demo=? ORDER BY date,id',(v['id'],period,state['demo']))
  previous=one(db,'SELECT * FROM transactions WHERE active=1 AND vehicle_id=? AND date<? AND odometer>0 AND gallons>0 AND demo=? ORDER BY date DESC,id DESC LIMIT 1',(v['id'],period+'-01',state['demo']))
  tso=one(db,'SELECT * FROM tso WHERE active=1 AND vehicle_id=? AND period=? AND kind=?',(v['id'],period,'efficiency'))
  base=one(db,'SELECT * FROM baselines WHERE active=1 AND energy_group=? AND status="ACTIVA" AND start<=? AND (end IS NULL OR end>=?) ORDER BY start DESC LIMIT 1',(v['energy_group'],period+'-01',end))
  group_override=one(db,"SELECT value FROM overrides WHERE vehicle_id=? AND period=? AND entity='period_group' AND field='energy_group' AND active=1 ORDER BY id DESC LIMIT 1",(v['id'],period))
  if group_override:
   v=dict(v);v['energy_group']=group_override['value']
   base=one(db,'SELECT * FROM baselines WHERE active=1 AND energy_group=? AND status="ACTIVA" AND start<=? AND (end IS NULL OR end>=?) ORDER BY start DESC LIMIT 1',(v['energy_group'],period+'-01',end))
  status_override=one(db,"SELECT value FROM overrides WHERE vehicle_id=? AND period=? AND entity='period_status' AND active=1 ORDER BY id DESC LIMIT 1",(v['id'],period))
  ov=one(db,'SELECT * FROM overrides WHERE vehicle_id=? AND period=? AND entity="result" AND active=1 ORDER BY id DESC LIMIT 1',(v['id'],period))
  result=calculate(tanks,previous,tso,base,json.loads(ov['value']) if ov else None,settings['max_monthly_km'],settings['max_daily_km'])
  assignments=rows(db,'SELECT a.*,p.code,p.name FROM assignments a JOIN projects p ON p.id=a.project_id WHERE vehicle_id=? AND start<=? AND (end IS NULL OR end>=?) ORDER BY start',(v['id'],end,period+'-01'))
  project=assignments[-1] if len(assignments)==1 else None
  if len(assignments)>1:
   result['notes'].append('Cambio de proyecto durante el mes: resultado energético sin atribuir; abastecimientos se asignan por fecha')
   result['quality']='REQUIERE REVISIÓN'
  if not project:
   result['notes'].append('Sin proyecto único vigente en el período')
   if result['km'] is not None:result['quality']='REQUIERE REVISIÓN'
  if not v['known']:
   result['notes'].append('Placa desconocida en la base maestra');result['quality']='REQUIERE REVISIÓN'
  result.update(plate=v['plate'],vehicle_id=v['id'],project=project['name'] if project else 'Sin asignar',project_id=project['project_id'] if project else None,energy_group=v['energy_group'],fuel=v['fuel'],operational_status=status_override['value'] if status_override else v['status'],purchased_gallons=sum(t['gallons'] for t in tanks),cost=sum(t['cost'] for t in tanks),tank_count=len(tanks),demo=bool(state['demo']),override_id=ov['id'] if ov else None)
  db.execute('INSERT INTO results(period,vehicle_id,project_id,data) VALUES (?,?,?,?)',(period,v['id'],result['project_id'],dump(result)))
 db.execute('UPDATE periods SET status="EN REVISIÓN",calculated_at=? WHERE period=?',(datetime.now().isoformat(timespec='seconds'),period))
 return {'processed':len(candidates),'results':result_list(db,period)}

def result_list(db,period):
 if one(db,"SELECT period FROM periods WHERE period=? AND status='BORRADOR'",(period,)):return []
 return [json.loads(r['data']) for r in rows(db,'SELECT data FROM results WHERE period=?',(period,))]
def transactions(db,period):
 return rows(db,'''SELECT t.*,v.plate, COALESCE((SELECT p.name FROM assignments a JOIN projects p ON p.id=a.project_id WHERE a.vehicle_id=t.vehicle_id AND a.start<=substr(t.date,1,10) AND (a.end IS NULL OR a.end>=substr(t.date,1,10)) LIMIT 1),'Sin asignar') project FROM transactions t JOIN vehicles v ON v.id=t.vehicle_id JOIN periods m ON m.period=substr(t.date,1,7) AND m.demo=t.demo WHERE t.active=1 AND substr(t.date,1,7)=? ORDER BY t.date''',(period,))
def state(db,period):
 period_check(period)
 p=one(db,'SELECT * FROM periods WHERE period=?',(period,))
 if p and p['status']=='CERRADO' and p['snapshot']:
  result=json.loads(p['snapshot']);result['period']['status']='CERRADO';result['periods']=rows(db,'SELECT period,status,demo,calculated_at FROM periods ORDER BY period DESC');return result
 return {'period':{k:v for k,v in (p or {'period':period,'status':'BORRADOR','demo':0}).items() if k!='snapshot'},'periods':rows(db,'SELECT period,status,demo,calculated_at FROM periods ORDER BY period DESC'),'results':result_list(db,period),'transactions':transactions(db,period),'imports':document_list(db,period),'issues':rows(db,'SELECT i.*,v.plate FROM issues i LEFT JOIN vehicles v ON v.id=i.vehicle_id WHERE i.period=? AND EXISTS(SELECT 1 FROM imports d WHERE d.id=i.import_id AND d.status="ACTIVO") ORDER BY i.id DESC',(period,)),'tso':rows(db,'SELECT t.*,v.plate FROM tso t JOIN vehicles v ON v.id=t.vehicle_id WHERE t.active=1 AND period=?',(period,))}

def mutate(db,action,data):
 period=data.get('period','2026-08')
 if action=='reload_document':return reload_document(db,int(data['import_id']),data.get('reason'),data.get('actor'))
 if action=='retire_document':return retire(db,int(data['import_id']),data.get('reason'),data.get('actor'))
 if action=='period':
  ensure_open(db,period);return {'message':'Período disponible'}
 if action=='process':return process(db,period)
 if action=='close':
  ensure_open(db,period)
  p=one(db,'SELECT * FROM periods WHERE period=?',(period,))
  if p['status']!='EN REVISIÓN' or not result_list(db,period):raise ValueError('Procese el período antes de cerrar')
  snap=state(db,period)
  snap['audit']=rows(db,'SELECT * FROM overrides WHERE period=?',(period,))
  db.execute('UPDATE periods SET status="CERRADO",snapshot=? WHERE period=?',(dump(snap),period));return {'message':'Período cerrado. Resultados y fuentes congelados.'}
 if action=='override':
  ensure_open(db,period);vid=int(data['vehicle_id']);source=data['source']
  before=one(db,'SELECT data FROM results WHERE period=? AND vehicle_id=?',(period,vid))
  if not before or not result_list(db,period):raise ValueError('Procese el período actualizado antes de corregir')
  before=json.loads(before['data'])
  if source not in ['TERPEL','TSO','MANUAL']:raise ValueError('Fuente inválida')
  km=numeric(data.get('km')) if source=='MANUAL' else before.get('terpel_km' if source=='TERPEL' else 'tso_km')
  if km is None or km<0:raise ValueError('La fuente seleccionada no contiene kilómetros utilizables')
  ov={'km':km,'source':source,'reason':data.get('reason')}
  oid=audit(db,'result','km',before.get('km'),ov,data.get('reason'),data.get('actor'),period,vid,before)
  process(db,period)
  after=one(db,'SELECT data FROM results WHERE period=? AND vehicle_id=?',(period,vid))
  db.execute('UPDATE overrides SET after_result=? WHERE id=?',(after['data'],oid))
  return {'message':'Corrección auditada y resultado recalculado'}
 if action=='vehicle':
  v=get_vehicle(db,data['plate'],True);old=dict(v)
  group=str(data.get('energy_group') or v.get('energy_group') or '').strip().upper()
  db.execute('UPDATE vehicles SET fuel=?,energy_group=?,status=?,known=1,brand=?,model=? WHERE id=?',(data.get('fuel',v['fuel']),group,data.get('status',v['status']),data.get('brand',v['brand']),data.get('model',v['model']),v['id']))
  raw=json.loads(v.get('raw') or '{}')
  for field,column in FIELDS.items():
   if field in data:raw[column]=data[field]
  db.execute('UPDATE vehicles SET raw=?,type=?,displacement=? WHERE id=?',(dump(raw),data.get('type',v['type']),numeric(data['displacement']) if 'displacement' in data else v['displacement'],v['id']))
  db.execute("UPDATE issues SET status='RESUELTO' WHERE vehicle_id=? AND reason LIKE 'Placa%desconocida%'",(v['id'],))
  audit(db,'vehicle','master',old,data,data.get('reason'),data.get('actor'),vid=v['id'])
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"')
  return {'message':'Vehículo guardado con auditoría; reprocesar períodos abiertos'}
 if action=='delete_vehicle':
  vid=int(data['vehicle_id'])
  for table in ['transactions','tso','assignments','results','overrides']:
   if one(db,f'SELECT id FROM {table} WHERE vehicle_id=? LIMIT 1',(vid,)):raise ValueError('El vehículo tiene histórico; utilice desactivar')
  db.execute('DELETE FROM vehicles WHERE id=?',(vid,));return {'message':'Vehículo sin histórico eliminado'}
 if action=='delete_all_vehicles':
  if not str(data.get('reason') or '').strip() or not str(data.get('actor') or '').strip():raise ValueError('Indique motivo y responsable')
  count=one(db,"SELECT count(*) n FROM vehicles")['n']
  if one(db,"SELECT 1 FROM transactions WHERE active=1 LIMIT 1") or one(db,"SELECT 1 FROM tso WHERE active=1 LIMIT 1") or one(db,"SELECT 1 FROM results LIMIT 1"):
   raise ValueError('No se puede borrar toda la flota mientras existan consumos, TSO o resultados activos. Retire primero esos documentos.')
  db.execute("UPDATE vehicles SET status='RETIRADO',known=0 WHERE 1=1")
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"')
  audit(db,'fleet','delete_all',count,None,data['reason'],data['actor'])
  return {'message':f'{count} vehículos retirados de la flota. Sus filas maestras e históricos quedan conservados.','count':count}
 if action=='delete_baseline':
  bid=int(data['baseline_id']); b=one(db,'SELECT * FROM baselines WHERE active=1 AND id=?',(bid,))
  if not b:raise ValueError('Línea base no encontrada o ya eliminada')
  if not str(data.get('reason') or '').strip() or not str(data.get('actor') or '').strip():raise ValueError('Indique motivo y responsable')
  db.execute('UPDATE baselines SET active=0,status="RETIRADA" WHERE id=?',(bid,))
  audit(db,'baseline','delete',b,None,data['reason'],data['actor'])
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"')
  return {'message':'Línea base eliminada de las vigentes; se conserva en auditoría'}
 if action=='assignment':
  start=date.fromisoformat(data['start']).isoformat()
  ensure_open(db,start[:7])
  old=rows(db,'SELECT * FROM assignments WHERE vehicle_id=?',(data['vehicle_id'],))
  assign(db,int(data['vehicle_id']),data['project'],start,'Fecha indicada manualmente')
  audit(db,'assignment','project',old,data,data.get('reason'),data.get('actor'),vid=int(data['vehicle_id']))
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"')
  return {'message':'Histórico de asignaciones actualizado'}
 if action=='edit_baseline':
  b=one(db,'SELECT * FROM baselines WHERE active=1 AND id=?',(data['id'],))
  if not b:raise ValueError('Línea base inexistente o modificada; actualice la página')
  if not str(data.get('reason') or '').strip() or not str(data.get('actor') or '').strip():raise ValueError('Indique motivo y responsable')
  fields=['sample_n','slope','intercept','z_value','sy_value','target','potential','max_tank_gallons']
  values={k:numeric(data.get(k,b.get(k))) for k in fields}
  validate_tank_limit(data.get('max_tank_gallons',b.get('max_tank_gallons')))
  if any(values[k] is None for k in ['slope','intercept','target']):raise ValueError('Pendiente, intercepto y meta deben ser numéricos')
  if any(v is not None and not math.isfinite(v) for v in values.values()):raise ValueError('Los parámetros deben ser números finitos')
  start=date.fromisoformat(data['start']).isoformat() if data.get('start') else None
  end=date.fromisoformat(data['end']).isoformat() if data.get('end') else None
  if end and not start:raise ValueError('Indique la fecha de inicio')
  if b['status']=='ACTIVA' and not start:raise ValueError('Una línea activa requiere fecha de inicio')
  if end and end<start:raise ValueError('Vigencia invertida')
  if start:check_baseline_overlap(db,b,start,end)
  version=b['version']+'-R2';revision=2
  while one(db,'SELECT id FROM baselines WHERE energy_group=? AND version=?',(b['energy_group'],version)):
   revision+=1;version=b['version']+'-R'+str(revision)
  new={**b,**values,'version':version,'version_label':version,'start':start,'end':end,'status':'ACTIVA' if start else 'PENDIENTE'}
  columns=['energy_group','version','version_label',*fields,'start','end','status','import_id','raw']
  cur=db.execute('INSERT INTO baselines ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(new[k] for k in columns))
  new['id']=cur.lastrowid
  db.execute('UPDATE baselines SET active=0 WHERE id=?',(b['id'],))
  if b['import_id']:db.execute('INSERT OR IGNORE INTO document_records(import_id,table_name,record_id) VALUES (?,"baselines",?)',(b['import_id'],new['id']))
  audit(db,'baseline','revision',b,new,data['reason'],data['actor'])
  from .documents import invalidate
  invalidate(db)
  return {'message':f'Revisión {version} guardada. Reprocese los meses abiertos; los cierres se conservan.'}
 if action=='baseline':
  b=one(db,'SELECT * FROM baselines WHERE active=1 AND id=?',(data['id'],))
  if not b:raise ValueError('Línea base inexistente')
  if b['status']!='PENDIENTE':raise ValueError('La versión ya tiene vigencia; cree una versión nueva')
  if any(b[k] is None for k in ['slope','intercept','target']):raise ValueError('La línea base está incompleta')
  start=date.fromisoformat(data['start']).isoformat();end=date.fromisoformat(data['end']).isoformat() if data.get('end') else None
  if end and end<start:raise ValueError('Vigencia invertida')
  check_baseline_overlap(db,b,start,end)
  db.execute('UPDATE baselines SET start=?,end=?,status="ACTIVA" WHERE id=?',(start,end,b['id']))
  audit(db,'baseline','validity',b,data,data.get('reason'),data.get('actor'))
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"');return {'message':'Vigencia registrada. Los períodos cerrados conservan su snapshot.'}
 if action=='new_baseline':
  vals=[numeric(data.get(k)) for k in ['sample_n','slope','intercept','z_value','sy_value','target','potential','max_tank_gallons']]
  validate_tank_limit(data.get('max_tank_gallons'))
  if any(vals[i] is None for i in [1,2,5]):raise ValueError('Pendiente, intercepto y meta deben ser numéricos')
  if not data.get('energy_group') or not data.get('version'):raise ValueError('Indique grupo y versión')
  from .importers import version_key
  db.execute('INSERT INTO baselines(energy_group,version,version_label,sample_n,slope,intercept,z_value,sy_value,target,potential,max_tank_gallons) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(data['energy_group'].upper(),version_key(data['version']),data['version'].strip(),*vals))
  audit(db,'baseline','create',None,data,data.get('reason'),data.get('actor'));return {'message':'Nueva versión creada, pendiente de vigencia'}
 if action=='settings':
  for k in ['max_monthly_km','max_daily_km']:
   v=numeric(data.get(k))
   if v is None or v<=0:raise ValueError('Los límites deben ser positivos')
   old=one(db,'SELECT value FROM settings WHERE key=?',(k,))['value']
   audit(db,'settings',k,old,v,data.get('reason'),data.get('actor'))
   db.execute('UPDATE settings SET value=? WHERE key=?',(str(v),k))
  db.execute('UPDATE periods SET status="BORRADOR" WHERE status<>"CERRADO"');return {'message':'Configuración guardada; reprocesar períodos abiertos'}
 raise ValueError('Acción desconocida')

def vehicle_detail(db,vid):
 v=one(db,'SELECT * FROM vehicles WHERE id=?',(vid,))
 if not v:raise ValueError('Vehículo no encontrado')
 return {'vehicle':enrich(v),'assignments':rows(db,'SELECT a.*,p.name,p.code FROM assignments a JOIN projects p ON p.id=a.project_id WHERE vehicle_id=? ORDER BY start',(vid,)),'transactions':rows(db,'SELECT t.*,i.name file FROM transactions t LEFT JOIN imports i ON i.id=t.import_id WHERE t.active=1 AND vehicle_id=? ORDER BY date',(vid,)),'tso':rows(db,'SELECT * FROM tso WHERE active=1 AND vehicle_id=?',(vid,)),'results':[{'period':r['period'],**json.loads(r['data'])} for r in rows(db,'SELECT * FROM results WHERE vehicle_id=? AND period IN (SELECT period FROM periods WHERE status<>"BORRADOR") ORDER BY period',(vid,))],'audit':rows(db,'SELECT * FROM overrides WHERE vehicle_id=? ORDER BY id DESC',(vid,))}
