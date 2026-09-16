"""Idempotent migration from the initial local schema. Preserves all source rows."""
def migrate(db):
 if 'max_tank_gallons' not in {r[1] for r in db.execute('PRAGMA table_info(baselines)')}:
  db.execute('ALTER TABLE baselines ADD COLUMN max_tank_gallons REAL')
 if db.execute('PRAGMA user_version').fetchone()[0]>=1:
  # Incremental additions for the versioned baseline metadata.
  for column in ['version_label TEXT','sample_n REAL','z_value REAL','sy_value REAL']:
   try: db.execute('ALTER TABLE baselines ADD COLUMN '+column)
   except Exception: pass
  return
 db.execute('PRAGMA foreign_keys=OFF')
 try:
  db.execute('BEGIN IMMEDIATE')
  if db.execute('PRAGMA user_version').fetchone()[0]>=1:
   db.commit();return
  rebuilds={
   'imports':('UNIQUE(kind,period,hash,demo)',"status TEXT NOT NULL DEFAULT 'ACTIVO', retired_at TEXT, retired_reason TEXT, retired_actor TEXT, replaces_id INTEGER, managed INTEGER NOT NULL DEFAULT 0"),
   'transactions':('fingerprint TEXT NOT NULL UNIQUE','fingerprint TEXT NOT NULL'),
   'tso':('UNIQUE(vehicle_id,period,kind)','active INTEGER NOT NULL DEFAULT 1')}
  for table,(old,new) in rebuilds.items():
   ddl=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0]
   ddl=ddl.replace(old,new)
   if table=='transactions':ddl=ddl.rstrip()[:-1]+', active INTEGER NOT NULL DEFAULT 1)'
   ddl=ddl.replace('CREATE TABLE '+table+' ','CREATE TABLE '+table+'_new ',1).replace('CREATE TABLE '+table+'(','CREATE TABLE '+table+'_new(',1)
   cols=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
   db.execute(ddl)
   db.execute('INSERT INTO '+table+'_new ('+','.join(cols)+') SELECT '+','.join(cols)+' FROM '+table)
   db.execute('DROP TABLE '+table)
   db.execute('ALTER TABLE '+table+'_new RENAME TO '+table)
  db.execute('ALTER TABLE baselines ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
  for column in ['version_label TEXT','sample_n REAL','z_value REAL','sy_value REAL']:
   try: db.execute('ALTER TABLE baselines ADD COLUMN '+column)
   except Exception: pass
  db.execute('ALTER TABLE overrides ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
  statements=[
   "CREATE UNIQUE INDEX imports_active_hash ON imports(kind,period,hash,demo) WHERE status='ACTIVO'",
   'CREATE UNIQUE INDEX transactions_active_hash ON transactions(fingerprint) WHERE active=1',
   'CREATE UNIQUE INDEX tso_active_vehicle_period ON tso(vehicle_id,period,kind) WHERE active=1',
   'CREATE INDEX tx_vehicle_date ON transactions(vehicle_id,date)',
   'CREATE TABLE document_records(import_id INTEGER NOT NULL REFERENCES imports(id),table_name TEXT NOT NULL,record_id INTEGER NOT NULL,PRIMARY KEY(import_id,table_name,record_id))',
   'CREATE INDEX document_records_record ON document_records(table_name,record_id)',
   'CREATE TABLE document_effects(id INTEGER PRIMARY KEY,import_id INTEGER NOT NULL REFERENCES imports(id),vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),before_data TEXT NOT NULL,after_data TEXT NOT NULL,UNIQUE(import_id,vehicle_id))',
   'CREATE TABLE document_events(id INTEGER PRIMARY KEY,import_id INTEGER NOT NULL REFERENCES imports(id),event TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,data TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)']
  for sql in statements:db.execute(sql)
  for table in ['transactions','tso','baselines']:
   db.execute('INSERT INTO document_records SELECT import_id,?,id FROM '+table+' WHERE import_id IS NOT NULL',(table,))
  # Old files with only duplicate rows have no reliable shared-row provenance; keep original statistics.
  db.execute('PRAGMA user_version=1')
  if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('La migración detectó referencias inconsistentes')
  db.commit()
 except Exception:db.rollback();raise
 finally:db.execute('PRAGMA foreign_keys=ON')
