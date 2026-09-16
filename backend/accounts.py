"""Isolated persistent workspaces, invite-only accounts and revocable sessions."""
import hashlib,hmac,json,os,re,secrets,sqlite3,time,uuid
from pathlib import Path
from contextlib import contextmanager
from .db import ROOT

ITERATIONS=600000
SESSION_SECONDS=12*3600

def enabled():return os.environ.get('FUEL_MULTIUSER')=='1'
def root():return Path(os.environ.get('FUEL_ACCOUNTS_DIR',ROOT/'data/accounts')).resolve()
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def password_hash(password,salt=None):
 if not isinstance(password,str) or not 12<=len(password)<=200:raise ValueError('Use una contraseña de entre 12 y 200 caracteres')
 salt=salt or secrets.token_hex(16)
 return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),ITERATIONS).hex()
def password_matches(password,stored):
 try:return hmac.compare_digest(password_hash(password,stored.split(':')[0]),stored)
 except (ValueError,AttributeError):return False

@contextmanager
def registry():
 root().mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(root()/'accounts.sqlite',timeout=30);db.row_factory=sqlite3.Row
 db.executescript('''
 CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,workspace TEXT UNIQUE NOT NULL,admin INTEGER NOT NULL DEFAULT 0,disabled INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS invitations(token TEXT PRIMARY KEY,workspace TEXT UNIQUE NOT NULL,name TEXT NOT NULL,admin INTEGER NOT NULL DEFAULT 0,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0,created_by TEXT);
 CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at REAL NOT NULL,actor TEXT,event TEXT NOT NULL,subject TEXT);
 ''')
 try:
  with db:yield db
 finally:db.close()

def workspace_path(workspace):
 if not re.fullmatch(r'[0-9a-f]{32}',workspace):raise ValueError('Perfil inválido')
 return root()/'workspaces'/workspace/'fuel.sqlite'

def clone_workspace(source):
 """SQLite online backup captures a consistent snapshot; original files are immutable."""
 source=Path(source).resolve()
 if not source.is_file():raise ValueError('No se encuentra la base de origen')
 workspace=uuid.uuid4().hex;target=workspace_path(workspace)
 target.parent.mkdir(parents=True,exist_ok=False)
 src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(target)
 try:
  src.backup(dst)
  originals=target.parent/'originals';originals.mkdir()
  for iid,path,expected in dst.execute('SELECT id,path,hash FROM imports').fetchall():
   content=Path(path).read_bytes()
   if hashlib.sha256(content).hexdigest()!=expected:raise ValueError(f'El original de la importación {iid} no coincide con su huella')
   saved=originals/(expected+'.xlsx')
   if not saved.exists():saved.write_bytes(content)
   dst.execute('UPDATE imports SET path=? WHERE id=?',(str(saved),iid))
  dst.commit()
  if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('La copia no pasó la verificación de integridad')
 finally:src.close();dst.close()
 return workspace

def create_invitation(source,name,actor=None,bootstrap=False):
 name=str(name or '').strip()
 if not name or len(name)>100:raise ValueError('Indique un nombre de hasta 100 caracteres para el perfil')
 with registry() as db:
  db.execute('BEGIN IMMEDIATE')
  if bootstrap:
   if db.execute('SELECT 1 FROM users LIMIT 1').fetchone() or db.execute('SELECT 1 FROM invitations WHERE admin=1 AND used=0 AND expires>?',(time.time(),)).fetchone():raise ValueError('Ya existe un acceso de administración')
  else:
   user=db.execute('SELECT * FROM users WHERE id=? AND admin=1 AND disabled=0',(actor,)).fetchone()
   if not user:raise PermissionError('Solo el administrador puede invitar usuarios')
   source=workspace_path(user['workspace'])
  workspace=clone_workspace(source)
  token=secrets.token_urlsafe(32)
  db.execute('INSERT INTO invitations VALUES (?,?,?,?,?,0,?)',(digest(token),workspace,name,int(bootstrap),time.time()+48*3600,actor))
  db.execute('INSERT INTO events(at,actor,event,subject) VALUES (?,?,?,?)',(time.time(),actor,'invitation_created',workspace))
 return token

def accept_invitation(token,username,password):
 username=str(username or '').strip().lower()
 if not re.fullmatch(r'[a-z0-9._-]{3,60}',username):raise ValueError('Usuario: 3 a 60 letras sin tildes, números, puntos o guiones')
 encoded=password_hash(password)
 with registry() as db:
  db.execute('BEGIN IMMEDIATE')
  invite=db.execute('SELECT * FROM invitations WHERE token=? AND used=0 AND expires>?',(digest(str(token)),time.time())).fetchone()
  if not invite:raise ValueError('La invitación venció o ya fue utilizada')
  if db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():raise ValueError('Ese nombre de usuario ya está ocupado')
  uid=uuid.uuid4().hex
  db.execute('INSERT INTO users(id,username,name,password,workspace,admin) VALUES (?,?,?,?,?,?)',(uid,username,invite['name'],encoded,invite['workspace'],invite['admin']))
  db.execute('UPDATE invitations SET used=1 WHERE token=?',(digest(str(token)),))
  db.execute('INSERT INTO events(at,actor,event,subject) VALUES (?,?,?,?)',(time.time(),uid,'account_created',uid))
 return login(username,password)

def login(username,password,client='local'):
 username=str(username or '').strip().lower();keys=[digest('user:'+username),digest('client:'+client)]
 with registry() as db:
  now=time.time()
  if any(db.execute('SELECT 1 FROM attempts WHERE key=? AND count>=10 AND until>?',(key,now)).fetchone() for key in keys):raise ValueError('Demasiados intentos. Espere 15 minutos antes de volver a intentar')
  user=db.execute('SELECT * FROM users WHERE username=? AND disabled=0',(username,)).fetchone()
  valid=password_matches(password,user['password'] if user else '0'*32+':'+'0'*64)
  if not user or not valid:
   for key in keys:
    db.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN until<? THEN 1 ELSE count+1 END,until=excluded.until',(key,now+900,now))
   db.commit()
   raise ValueError('Usuario o contraseña incorrectos')
  for key in keys:db.execute('DELETE FROM attempts WHERE key=?',(key,))
  token=secrets.token_urlsafe(32)
  db.execute('DELETE FROM sessions WHERE expires<?',(now,))
  db.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(token),user['id'],now+SESSION_SECONDS))
 return token

def session_user(token):
 if not token:return None
 with registry() as db:
  row=db.execute('SELECT u.id,u.username,u.name,u.workspace,u.admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.disabled=0',(digest(token),time.time())).fetchone()
  return dict(row) if row else None

def logout(token):
 with registry() as db:db.execute('DELETE FROM sessions WHERE token=?',(digest(token),))

def change_password(user,password,new_password):
 encoded=password_hash(new_password)
 with registry() as db:
  db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()
  if not row or not password_matches(password,row['password']):raise ValueError('La contraseña actual no es correcta')
  db.execute('UPDATE users SET password=? WHERE id=?',(encoded,user['id']))
  db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))

def user_summary(user):return {k:user[k] for k in ['id','username','name','admin']}

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Preparar acceso inicial privado')
 parser.add_argument('--source',required=True);parser.add_argument('--url',required=True);parser.add_argument('--output',required=True)
 args=parser.parse_args()
 token=create_invitation(args.source,'Administrador PROING',bootstrap=True)
 out=Path(args.output)
 with out.open('x') as f:f.write(args.url.rstrip('/')+'/login.html#invite='+token+'\n')
 out.chmod(0o600)
 print('Acceso inicial guardado en el archivo indicado. Expira en 48 horas.')
