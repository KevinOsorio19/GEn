"""Pure interval and energy engine. No filesystem, database or UI dependencies."""
from datetime import datetime
from math import isfinite

def number(v):return isinstance(v,(float,int)) and isfinite(v)
def calculate(tanks,previous=None,tso=None,baseline=None,override=None,max_km=15000,max_daily=1200):
 result=_calculate(tanks,previous,tso,baseline,override,max_km,max_daily)
 limit=(baseline or {}).get('max_tank_gallons')
 alerts=[]
 if number(limit) and limit>0:
  for tank in tanks:
   if number(tank.get('gallons')) and tank['gallons']>limit:
    alerts.append(dict(transaction_id=tank.get('id'),date=tank['date'],gallons=tank['gallons'],limit=limit))
    result['notes'].append(f"Tanqueada supera el máximo del grupo {(baseline or {}).get('energy_group','')}: {tank['date']}, {tank['gallons']:g} gal; máximo {limit:g} gal por tanqueada.")
 if alerts:result['quality']='REQUIERE REVISIÓN'
 result['tank_capacity_alerts']=alerts
 return result

def _calculate(tanks,previous=None,tso=None,baseline=None,override=None,max_km=15000,max_daily=1200):
 tanks=sorted(tanks,key=lambda t:(t['date'],t.get('id',0)))
 result=dict(km=None,terpel_km=None,tso_km=tso.get('km') if tso else None,source=None,gallons=None,theoretical=None,ic=None,target=None,compliance='SIN EVALUAR',quality='INFORMACIÓN INSUFICIENTE',notes=[],baseline=baseline,transaction_ids=[t.get('id') for t in tanks],initial=None,final=None,formula='Teóricos = m × km + b; IC = (teóricos − reales) / teóricos')
 if not tanks:
  result['notes'].append('Sin abastecimientos Terpel registrados durante el período. TSO no acredita combustible real.')
  return result
 if len(tanks)==1 and previous is None:
  result['notes'].append('Una sola tanqueada sin tanqueada válida anterior. No se inventa un intervalo.')
  return result
 initial=tanks[0] if len(tanks)>1 else previous
 final=tanks[-1]
 considered=tanks[1:] if len(tanks)>1 else tanks
 chain=[initial]+considered
 result.update(initial=initial,final=final,gallons=sum(t['gallons'] for t in considered),consumed_transaction_ids=[t.get('id') for t in considered])
 reasons=[]
 for a,b in zip(chain,chain[1:]):
  if not number(a.get('odometer')) or not number(b.get('odometer')) or min(a['odometer'],b['odometer'])<=0:
   reasons.append('Odómetro nulo, cero o inválido');continue
  delta=b['odometer']-a['odometer']
  elapsed=(datetime.fromisoformat(b['date'])-datetime.fromisoformat(a['date'])).total_seconds()/86400
  if delta<0:reasons.append('Kilometraje negativo entre tanqueadas')
  elif delta==0:reasons.append('Odómetro repetido con combustible consumido')
  elif elapsed<=0 or delta>max_daily*max(elapsed,1):reasons.append('Salto de odómetro físicamente improbable')
 if number(initial.get('odometer')) and number(final.get('odometer')):
  result['terpel_km']=final['odometer']-initial['odometer']
  if result['terpel_km']>max_km:reasons.append('Distancia Terpel superior al límite mensual')
 if not reasons:
  result.update(km=result['terpel_km'],source='TERPEL',quality='ALTA CONFIANZA')
 else:
  result['notes']+=list(dict.fromkeys(reasons))
  if tso and number(tso.get('km')) and 0<tso['km']<=max_km:
   result.update(km=tso['km'],source='TSO',quality='MEDIA CONFIANZA')
   result['notes'].append('Respaldo TSO eficiencia; su cobertura puede diferir del intervalo Terpel. Revisar Desde/Hasta.')
   result['tso_interval']={'start':tso.get('start'),'end':tso.get('end')}
  else:
   result['quality']='REQUIERE REVISIÓN'
   result['notes'].append('TSO eficiencia ausente o inválido')
 if override:
  value=override.get('km')
  if number(value) and value>=0:
   result.update(km=value,source=override.get('source','MANUAL'),quality='REVISADO')
   result['notes'].append('Selección autorizada: '+override.get('reason',''))
 if result['km'] is None:return result
 if not baseline or not all(number(baseline.get(k)) for k in ['slope','intercept','target']):
  result['quality']='REQUIERE REVISIÓN'
  result['notes'].append('Sin línea base vigente y completa para el grupo energético')
  return result
 theoretical=baseline['slope']*result['km']+baseline['intercept']
 if theoretical<=0:
  result['quality']='REQUIERE REVISIÓN';result['notes'].append('Galones teóricos no positivos; no se calcula IC');return result
 ic=(theoretical-result['gallons'])/theoretical
 result.update(theoretical=theoretical,ic=ic,target=baseline['target'],compliance='CUMPLE META' if ic>=baseline['target'] else 'MEJORA SIN META' if ic>=0 else 'SOBRECONSUMO')
 return result
