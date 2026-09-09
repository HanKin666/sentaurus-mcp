"""Persistent batch experiments, independent of dashboards and model providers."""
import hashlib,json,os,re,sqlite3,subprocess,sys,time,uuid
from pathlib import Path

def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):raise ValueError('Invalid identifier')
    return value

class Service:
    def __init__(self,config_path=None):
        value=config_path or os.getenv('SENTAURUS_MCP_CONFIG')
        if not value:raise ValueError('Set SENTAURUS_MCP_CONFIG')
        self.config_path=Path(value).resolve()
        self.config=json.loads(self.config_path.read_text(encoding='utf-8'))
        root=Path(self.config['root'])
        if not root.is_absolute():raise ValueError('root must be absolute')
        self.root=root.resolve();self.root.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,project TEXT,state TEXT,manifest TEXT,status TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS worker (id INTEGER PRIMARY KEY,token TEXT,heartbeat REAL)')

    def connect(self):
        db=sqlite3.connect(str(self.root/'experiments.sqlite3'),timeout=10);db.row_factory=sqlite3.Row
        return db

    def directory(self,project,rid):
        path=(self.root/identifier(project)/identifier(rid)).resolve()
        if self.root not in path.parents:raise ValueError('Path escapes root')
        return path

    def get(self,rid):
        with self.connect() as db:row=db.execute('SELECT * FROM runs WHERE id=?',(identifier(rid),)).fetchone()
        if row is None:raise ValueError('Unknown experiment')
        return {'run_id':row['id'],'project':row['project'],'state':row['state'],
                'manifest':json.loads(row['manifest']),'status':json.loads(row['status']),
                'directory':str(self.directory(row['project'],row['id']))}

    def list(self,offset=0,limit=20):
        if offset<0 or not 1<=limit<=100:raise ValueError('Invalid pagination')
        with self.connect() as db:
            total=db.execute('SELECT count(*) FROM runs').fetchone()[0]
            rows=db.execute('SELECT id,project,state,status FROM runs ORDER BY rowid DESC LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        return {'total':total,'items':[{**dict(r),'status':json.loads(r['status'])} for r in rows]}

    def create(self,project,rid,files,stages):
        folder=self.directory(project,rid)
        if not files or sum(len(v.encode()) for v in files.values())>2_000_000:raise ValueError('Inputs must be nonempty and <=2MB')
        for name in files:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}',name) or name.lower() in ('manifest.json','runner.log','state.json') or name.startswith('stage-'):raise ValueError('Invalid or reserved file name')
        if not 1<=len(stages)<=16:raise ValueError('Provide 1..16 stages')
        commands=[]
        for stage in stages:
            tool=stage['tool'];name=stage['input_file'];argv=self.config.get('tools',{}).get(tool)
            if name not in files or not isinstance(argv,list) or not argv or not all(isinstance(v,str) for v in argv):raise ValueError('Invalid input or tool profile')
            if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():raise ValueError('Configured executable must exist at absolute path')
            commands.append({'tool':tool,'input_file':name,'argv':[v.replace('{input}',name) for v in argv]})
        manifest={'run_id':rid,'project':project,'created_at':time.time(),'stages':commands,
                  'input_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()},
                  'scope':'Native batch folder, not a generated SWB project','time_policy':'no_wall_clock_kill'}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM runs WHERE id=?',(rid,)).fetchone():raise ValueError('ID already exists')
            folder.mkdir(parents=True,exist_ok=False)
            for name,content in files.items():(folder/name).write_bytes(content.encode())
            (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',(rid,project,'prepared',json.dumps(manifest),'{}'))
        return self.get(rid)

    def update(self,rid,state,status):
        with self.connect() as db:db.execute('UPDATE runs SET state=?,status=? WHERE id=?',(state,json.dumps(status),rid))

    def submit(self,rid):
        run=self.get(rid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM runs WHERE id=?',(rid,)).fetchone()
            if row[0]!='prepared':return {'run_id':rid,'state':row[0],'submitted':False}
            worker=db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
            if not worker or time.time()-worker[0]>10:raise ValueError('Independent sentaurus-worker is not online')
            for name,digest in run['manifest']['input_sha256'].items():
                if hashlib.sha256((Path(run['directory'])/name).read_bytes()).hexdigest()!=digest:raise ValueError('Input changed after preparation')
            db.execute('UPDATE runs SET state=?,status=? WHERE id=?',('queued',json.dumps({'queued_at':time.time(),'validation':'not_reviewed'}),rid))
        return {'run_id':rid,'state':'queued','submitted':True}

    def launch_queued(self,rid):
        """Worker-only launch path; MCP never creates solver child processes."""
        run=self.get(rid);folder=Path(run['directory'])
        for name,digest in run['manifest']['input_sha256'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('Input changed after preparation')
        token=uuid.uuid4().hex;status={'launch_token':token,'submitted_at':time.time(),'validation':'not_reviewed'}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT state FROM runs WHERE id=?',(rid,)).fetchone()[0]
            if current!='queued':return {'run_id':rid,'state':current,'submitted':False}
            count=db.execute("SELECT count(*) FROM runs WHERE state IN ('starting','running')").fetchone()[0]
            if count>=int(self.config.get('max_parallel',1)):return {'run_id':rid,'state':'queued','submitted':False,'reason':'parallel_limit'}
            db.execute('UPDATE runs SET state=?,status=? WHERE id=?',('starting',json.dumps(status),rid))
        options={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS}
        try:
            with (folder/'runner.log').open('ab') as log:
                subprocess.Popen([sys.executable,'-m','sentaurus_mcp.runner',str(self.config_path),rid,token],stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,**options)
        except OSError as exc:
            status.update(error=str(exc),finished_at=time.time());self.update(rid,'failed',status);raise
        return {'run_id':rid,'state':'starting','submitted':True}

    def log(self,rid,stage_index=0,offset=0,limit=8000):
        run=self.get(rid)
        if not 0<=stage_index<len(run['manifest']['stages']) or offset<0 or not 1<=limit<=16000:raise ValueError('Invalid cursor')
        path=Path(run['directory'])/f'stage-{stage_index}.log'
        if not path.exists():return {'text':'','next_offset':offset,'available':False}
        with path.open('rb') as stream:stream.seek(offset);raw=stream.read(limit)
        return {'text':raw.decode('utf-8','replace'),'next_offset':offset+len(raw),'available':True,'cursor_unit':'bytes'}

    def artifacts(self,rid):
        root=Path(self.get(rid)['directory']);items=[]
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:continue
            items.append({'name':path.relative_to(root).as_posix(),'bytes':path.stat().st_size,'path':str(path)})
            if len(items)>=1000:break
        return {'run_id':rid,'items':items,'limit':1000,'scope':'Current files; ongoing writes may be incomplete'}
