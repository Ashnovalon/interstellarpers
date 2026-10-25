import os
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

@contextmanager
def db():
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=5) as conn:
        yield conn

def initialize():
    with db() as conn:
        conn.execute(Path(__file__).with_name('schema.sql').read_text())

def heartbeat(service, detail=None):
    with db() as conn:
        conn.execute('INSERT INTO heartbeat(service,detail) VALUES (%s,%s) ON CONFLICT(service) DO UPDATE SET updated_at=now(),detail=excluded.detail', (service,Jsonb(detail or {})))

def projected():
    with db() as conn:
        rows = conn.execute('SELECT kind,data,revision FROM projected').fetchall()
        imported = conn.execute('SELECT coalesce(max(revision),0) AS n FROM records').fetchone()['n']
        version = max((r['revision'] for r in rows),default=0)
        first_missing = conn.execute('''SELECT min(r.revision) AS n FROM records r LEFT JOIN projected p
          ON p.kind=r.kind AND p.id=r.id WHERE p.revision IS DISTINCT FROM r.revision''').fetchone()['n']
        # A high revision on another key must not hide an earlier unprocessed key.
        if first_missing is not None: version = min(version,first_missing-1)
    groups = {}
    for row in rows:
        groups.setdefault(row['kind'],[]).append(row['data'])
    return groups, version, imported
