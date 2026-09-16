import sqlite3, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS periods (period TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'BORRADOR', demo INTEGER NOT NULL DEFAULT 0, snapshot TEXT, calculated_at TEXT);
CREATE TABLE IF NOT EXISTS imports (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, period TEXT NOT NULL, name TEXT NOT NULL, hash TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, report TEXT, demo INTEGER NOT NULL DEFAULT 0, UNIQUE(kind,period,hash,demo));
CREATE TABLE IF NOT EXISTS vehicles (id INTEGER PRIMARY KEY, plate TEXT NOT NULL UNIQUE, type TEXT, model TEXT, brand TEXT, fuel TEXT, displacement REAL, source_group TEXT, energy_group TEXT, status TEXT DEFAULT 'ACTIVO', known INTEGER NOT NULL DEFAULT 1, raw TEXT, import_id INTEGER REFERENCES imports(id));
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments (id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), project_id INTEGER NOT NULL REFERENCES projects(id), start TEXT NOT NULL, end TEXT, assumption TEXT, CHECK(end IS NULL OR end>=start));
CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), date TEXT NOT NULL, station TEXT, city TEXT, fuel TEXT, gallons REAL NOT NULL CHECK(gallons>0), cost REAL NOT NULL CHECK(cost>=0), odometer REAL, source TEXT NOT NULL DEFAULT 'TERPEL', original_id TEXT, fingerprint TEXT NOT NULL UNIQUE, import_id INTEGER REFERENCES imports(id), row_number INTEGER, raw TEXT, flags TEXT, demo INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tx_vehicle_date ON transactions(vehicle_id,date);
CREATE TABLE IF NOT EXISTS tso (id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), period TEXT NOT NULL, kind TEXT NOT NULL, km REAL, gallons REAL, efficiency REAL, cost REAL, start TEXT, end TEXT, drive_hours REAL, idle_hours REAL, engine_hours REAL, import_id INTEGER REFERENCES imports(id), row_number INTEGER, raw TEXT, UNIQUE(vehicle_id,period,kind));
CREATE TABLE IF NOT EXISTS baselines (id INTEGER PRIMARY KEY, energy_group TEXT NOT NULL, version TEXT NOT NULL, version_label TEXT, sample_n REAL, slope REAL, intercept REAL, z_value REAL, sy_value REAL, target REAL, potential REAL, start TEXT, end TEXT, status TEXT NOT NULL DEFAULT 'PENDIENTE', import_id INTEGER REFERENCES imports(id), raw TEXT, UNIQUE(energy_group,version));
CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, period TEXT NOT NULL REFERENCES periods(period), vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), project_id INTEGER REFERENCES projects(id), data TEXT NOT NULL, UNIQUE(period,vehicle_id));
CREATE TABLE IF NOT EXISTS overrides (id INTEGER PRIMARY KEY, period TEXT, vehicle_id INTEGER REFERENCES vehicles(id), entity TEXT NOT NULL, field TEXT NOT NULL, original TEXT, value TEXT, reason TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, before_result TEXT, after_result TEXT);
CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, import_id INTEGER REFERENCES imports(id), period TEXT, vehicle_id INTEGER REFERENCES vehicles(id), row_number INTEGER, reason TEXT NOT NULL, raw TEXT, status TEXT DEFAULT 'PENDIENTE');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES ('max_monthly_km','15000');
INSERT OR IGNORE INTO settings VALUES ('max_daily_km','1200');
'''
def connect(path=None):
 p=Path(path or os.environ.get('FUEL_DB',ROOT/'data/fuel.sqlite'))
 p.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(p,timeout=30)
 db.row_factory=sqlite3.Row
 db.executescript(SCHEMA)
 from .migrations import migrate
 migrate(db)
 # Backfill the energy group from the uploaded master when an older importer
 # stored it only in the original JSON payload.
 import json
 for row in db.execute("SELECT id,raw FROM vehicles WHERE energy_group IS NULL AND raw IS NOT NULL").fetchall():
  try:
   raw=json.loads(row[1]); group=str(raw.get('GRUPO SIPROING') or raw.get('GRUPO') or '').strip().upper()
   if group: db.execute('UPDATE vehicles SET energy_group=?,source_group=? WHERE id=?',(group,group,row[0]))
  except Exception: pass
 db.commit()
 return db

def rows(db,sql,args=()):return [dict(r) for r in db.execute(sql,args).fetchall()]
def one(db,sql,args=()):
 r=db.execute(sql,args).fetchone()
 return dict(r) if r else None
