"""Start independently of the MCP client: python -m sentaurus_mcp.worker."""
import time,uuid
from .service import Service

def main():
    service=Service();token=uuid.uuid4().hex
    with service.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
        if existing and time.time()-existing[0]<10:raise RuntimeError('A worker is already active')
        db.execute('INSERT OR REPLACE INTO worker VALUES (1,?,?)',(token,time.time()))
    try:
        while True:
            with service.connect() as db:
                if db.execute('UPDATE worker SET heartbeat=? WHERE id=1 AND token=?',(time.time(),token)).rowcount!=1:raise RuntimeError('Worker lease lost')
                ids=[r[0] for r in db.execute("SELECT id FROM runs WHERE state='queued' ORDER BY rowid")]
            for rid in ids:
                try:service.launch_queued(rid)
                except (ValueError,OSError) as exc:service.update(rid,'failed',{'error':str(exc),'validation':'not_reviewed','finished_at':time.time()})
            time.sleep(.5)
    finally:
        with service.connect() as db:db.execute('DELETE FROM worker WHERE token=?',(token,))

if __name__=='__main__':main()
