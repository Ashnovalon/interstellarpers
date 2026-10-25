"""Replay-safe history: stable event IDs, ClickHouse FINAL, Iceberg upsert."""
import json
import os
import boto3
import clickhouse_connect
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, TableAlreadyExistsError
from .db import db

SCHEMA=pa.schema([pa.field('event_id',pa.string(),nullable=False),pa.field('kind',pa.string()),
                 pa.field('revision',pa.int64()),pa.field('payload',pa.string())])

def catalog():
    return load_catalog('real',type='sql',uri=os.environ['ICEBERG_CATALOG_URL'],warehouse='s3://real-history/warehouse',
      **{'s3.endpoint':os.getenv('S3_ENDPOINT','http://objectstore:9000'),'s3.access-key-id':os.environ['AWS_ACCESS_KEY_ID'],
         's3.secret-access-key':os.environ['AWS_SECRET_ACCESS_KEY'],'s3.region':'us-east-1','s3.force-virtual-addressing':'false'})

def clients():
    s3=boto3.client('s3',endpoint_url=os.getenv('S3_ENDPOINT','http://objectstore:9000'))
    try: s3.head_bucket(Bucket='real-history')
    except Exception: s3.create_bucket(Bucket='real-history')
    cat=catalog()
    try: cat.create_namespace('operations')
    except NamespaceAlreadyExistsError: pass
    try: cat.create_table('operations.events',SCHEMA,properties={'format-version':'2'})
    except TableAlreadyExistsError: pass
    ch=clickhouse_connect.get_client(host=os.getenv('CLICKHOUSE_HOST','clickhouse'))
    ch.command('''CREATE TABLE IF NOT EXISTS real_events (event_id String,kind String,revision UInt64,payload String)
      ENGINE=ReplacingMergeTree(revision) ORDER BY event_id''')
    return s3,cat,ch

def archive(event,s3,cat,ch):
    raw=json.dumps(event,separators=(',',':'))
    with db() as conn:
        done={r['sink'] for r in conn.execute('SELECT sink FROM sink_receipts WHERE event_id=%s',(event['id'],)).fetchall()}
    for name in ('object','clickhouse','iceberg'):
        if name in done: continue
        if name=='object': s3.put_object(Bucket='real-history',Key='events/'+event['id']+'.json',Body=raw.encode(),ContentType='application/json')
        if name=='clickhouse': ch.insert('real_events',[[event['id'],event['kind'],event['revision'],raw]],column_names=['event_id','kind','revision','payload'])
        if name=='iceberg':
            table=cat.load_table('operations.events')
            # Upsert by stable ID makes replays after a crash safe across the sink/receipt gap.
            table.upsert(pa.Table.from_pylist([{'event_id':event['id'],'kind':event['kind'],'revision':event['revision'],'payload':raw}],schema=SCHEMA),join_cols=['event_id'])
        with db() as conn: conn.execute('INSERT INTO sink_receipts(event_id,sink) VALUES (%s,%s) ON CONFLICT DO NOTHING',(event['id'],name))
