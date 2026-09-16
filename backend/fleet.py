"""Additional master fields retained in the original row, with stable API names."""
import json
FIELDS={'plate_type':'TIPO PLACA','line':'LÍNEA VEHÍCULO','reference_project':'PROYECTO','owner':'PROPIETARIO','ownership_type':'TIPO PROPIEDAD'}
def enrich(vehicle):
 raw=json.loads(vehicle.get('raw') or '{}')
 return {**vehicle,**{key:raw.get(column) for key,column in FIELDS.items()}}
