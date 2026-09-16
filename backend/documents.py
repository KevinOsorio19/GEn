"""Import lifecycle: append-only document events and inactive original records."""
import json
from .db import rows,one

def encode(v):return json.dumps(v,ensure_ascii=False,default=str)
def invalidate(db):
 affected=rows(db,"SELECT period FROM periods WHERE status<>'CERRADO'")
 db.execute("UPDATE periods SET status='BORRADOR',calculated_at=NULL WHERE status<>'CERRADO'")
 return [p['period'] for p in affected]

def link(db,iid,table,rid):
 db.execute('INSERT OR IGNORE INTO document_records(import_id,table_name,record_id) VALUES (?,?,?)',(iid,table,rid))

def journal(db,iid,vid,before,after):
 # Collapse multiple rows for the same vehicle into one before/after effect.
 existing=one(db,'SELECT id FROM document_effects WHERE import_id=? AND vehicle_id=?',(iid,vid))
 if existing:db.execute('UPDATE document_effects SET after_data=? WHERE id=?',(encode(after),existing['id']))
 else:db.execute('INSERT INTO document_effects(import_id,vehicle_id,before_data,after_data) VALUES (?,?,?,?)',(iid,vid,encode(before),encode(after)))

def master_state(db,vid):
 return {'vehicle':one(db,'SELECT * FROM vehicles WHERE id=?',(vid,)), 'assignments':rows(db,'SELECT * FROM assignments WHERE vehicle_id=? ORDER BY id',(vid,))}

def document_list(db,period):
 from .importers import period_check
 period_check(period)
 # This screen is deliberately limited to the monthly package. Permanent
 # fleet and baseline imports are managed from their own modules.
 docs=rows(db,"SELECT id,kind,period,name,hash,created_at,report,demo,status,retired_at,retired_reason,retired_actor,replaces_id,managed FROM imports WHERE period=? AND kind IN ('terpel','efficiency','summary','assignments') ORDER BY id DESC",(period,))
 closed=one(db,"SELECT period FROM periods WHERE period=? AND status='CERRADO'",(period,))
 for d in docs:
  d['report']=json.loads(d['report'] or '{}')
  d['blocked_reason']=blocked_reason(db,d,closed)
  d['can_retire']=d['status']=='ACTIVO' and not d['blocked_reason']
  d['active_records']=one(db,'SELECT count(*) n FROM document_records WHERE import_id=?',(d['id'],))['n'] if d['status']=='ACTIVO' else 0
 return docs

def blocked_reason(db,d,closed=None):
 if d['status']!='ACTIVO':return 'El documento ya está retirado.'
 if closed or one(db,"SELECT period FROM periods WHERE period=? AND status='CERRADO'",(d['period'],)):return 'El período está cerrado; sus documentos están protegidos.'
 # Monthly source files do not own permanent master state and can always be
 # retired while the period is open, including legacy uploads.
 if d['kind'] in ['terpel','efficiency','summary','assignments']:
  return None
 if d['kind'] in ['vehicles','assignments']:
  if not d['managed']:return 'Carga anterior a la gestión de documentos: no conserva el estado maestro previo necesario para deshacerla con seguridad. Las nuevas cargas sí permiten retirada.'
  for effect in rows(db,'SELECT * FROM document_effects WHERE import_id=?',(d['id'],)):
   if one(db,"SELECT e.id FROM document_effects e JOIN imports i ON i.id=e.import_id WHERE e.vehicle_id=? AND i.id>? AND i.status='ACTIVO' LIMIT 1",(effect['vehicle_id'],d['id'])):return 'Hay cargas posteriores del mismo vehículo. Retírelas primero para conservar el histórico.'
   expected=json.loads(effect['after_data']);current=master_state(db,effect['vehicle_id'])
   # Assignment-only files do not own vehicle attributes.
   if d['kind']=='assignments':expected={'assignments':expected['assignments']};current={'assignments':current['assignments']}
   if current!=expected:return 'Hay cambios posteriores en vehículos o proyectos. Retire primero las cargas posteriores o conserve este documento para no deshacer esos cambios.'
 return None

def detail(db,iid):
 d=one(db,'SELECT * FROM imports WHERE id=?',(iid,))
 if not d:raise ValueError('Documento no encontrado')
 result=next(x for x in document_list(db,d['period']) if x['id']==iid)
 result['issues']=rows(db,'SELECT row_number,reason,status,raw FROM issues WHERE import_id=?',(iid,))
 result['events']=rows(db,'SELECT * FROM document_events WHERE import_id=? ORDER BY id',(iid,))
 records=[]
 for ref in rows(db,'SELECT * FROM document_records WHERE import_id=? ORDER BY table_name,record_id LIMIT 200',(iid,)):
  if ref['table_name'] not in ['transactions','tso','baselines']:continue
  r=one(db,f"SELECT * FROM {ref['table_name']} WHERE id=?",(ref['record_id'],))
  if r:records.append({'table':ref['table_name'],**r})
 result['records']=records
 result['effects']=rows(db,'SELECT vehicle_id,before_data,after_data FROM document_effects WHERE import_id=? LIMIT 100',(iid,))
 return result

def retire(db,iid,reason,actor):
 if not str(reason or '').strip() or not str(actor or '').strip():raise ValueError('Indique motivo y responsable de la retirada')
 d=one(db,'SELECT * FROM imports WHERE id=?',(iid,))
 if not d:raise ValueError('Documento no encontrado')
 blocked=blocked_reason(db,d)
 if blocked:raise ValueError(blocked)
 # Check all master dependencies before changing anything.
 db.execute("UPDATE imports SET status='RETIRADO',retired_at=CURRENT_TIMESTAMP,retired_reason=?,retired_actor=? WHERE id=?",(reason,actor,iid))
 for ref in rows(db,'SELECT * FROM document_records WHERE import_id=?',(iid,)):
  table=ref['table_name']
  if table not in ['transactions','tso','baselines']:continue
  other=one(db,"SELECT 1 FROM document_records r JOIN imports i ON i.id=r.import_id WHERE r.table_name=? AND r.record_id=? AND i.status='ACTIVO' LIMIT 1",(table,ref['record_id']))
  if not other:db.execute(f'UPDATE {table} SET active=0 WHERE id=?',(ref['record_id'],))
 for effect in rows(db,'SELECT * FROM document_effects WHERE import_id=? ORDER BY id DESC',(iid,)):
  before=json.loads(effect['before_data']);vid=effect['vehicle_id']
  db.execute('DELETE FROM assignments WHERE vehicle_id=?',(vid,))
  for a in before['assignments']:
   db.execute('INSERT INTO assignments('+','.join(a)+') VALUES ('+','.join('?' for _ in a)+')',tuple(a.values()))
  if d['kind']=='vehicles':
   v=before['vehicle'];fields=[k for k in v if k!='id']
   db.execute('UPDATE vehicles SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',tuple(v[k] for k in fields)+(vid,))
 # Keep issues and normalized rows for the audit trail; active review filters them out.
 affected=invalidate(db)
 # Source choices must be re-evaluated after input removal, never silently reused.
 db.execute("UPDATE overrides SET active=0 WHERE entity='result' AND period IN (SELECT period FROM periods WHERE status<>'CERRADO')")
 db.execute('INSERT INTO document_events(import_id,event,actor,reason,data) VALUES (?,?,?,?,?)',(iid,'RETIRADO',actor,reason,encode({'affected_periods':affected})))
 return {'message':'Documento retirado. Reprocese los períodos abiertos afectados; las selecciones manuales de km deben revisarse de nuevo.','affected_periods':affected}

def replace_file(db,iid,path,name,reason,actor):
 # Savepoint makes standalone callers as atomic as the HTTP transaction.
 from .importers import import_file
 old=one(db,'SELECT * FROM imports WHERE id=?',(iid,))
 if not old:raise ValueError('Documento no encontrado')
 db.execute('SAVEPOINT replace_document')
 try:
  retire(db,iid,reason,actor)
  report=import_file(db,path,old['kind'],old['period'],bool(old['demo']),name)
  if report.get('already_imported'):raise ValueError('El archivo elegido ya está activo. El documento anterior se conserva; seleccione otra versión.')
  if report['imported']==0 and report['duplicates']==0:raise ValueError('El reemplazo no contiene registros válidos. El documento anterior sigue activo.')
  db.execute('UPDATE imports SET replaces_id=? WHERE id=?',(iid,report['id']))
  db.execute('INSERT INTO document_events(import_id,event,actor,reason,data) VALUES (?,?,?,?,?)',(report['id'],'REEMPLAZO',actor,reason,encode({'previous_import_id':iid})))
  db.execute('RELEASE replace_document')
  return {**report,'message':'Documento reemplazado. Reprocese los períodos abiertos y revise las advertencias.'}
 except Exception:
  db.execute('ROLLBACK TO replace_document');db.execute('RELEASE replace_document');raise

def reload_document(db,iid,reason,actor):
 from .importers import import_file
 if not str(reason or '').strip() or not str(actor or '').strip():raise ValueError('Indique motivo y responsable de la nueva carga')
 d=one(db,'SELECT * FROM imports WHERE id=?',(iid,))
 if not d or d['status']!='RETIRADO':raise ValueError('Solo se puede volver a cargar un documento retirado')
 report=import_file(db,d['path'],d['kind'],d['period'],bool(d['demo']),d['name'])
 if not report.get('already_imported'):
  db.execute('INSERT INTO document_events(import_id,event,actor,reason,data) VALUES (?,?,?,?,?)',(report['id'],'RECARGADO',actor,reason,encode({'previous_import_id':iid})))
 return {**report,'message':report.get('message','Original cargado nuevamente. Reprocese el período.')}
