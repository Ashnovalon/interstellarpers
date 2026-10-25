import asyncio
import json
import os
import uuid
import time
from contextlib import asynccontextmanager
from datetime import date
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from psycopg.types.json import Jsonb
from .contracts import CONTRACTS, validate_batch, record_hash, scenario_metrics
from .db import db, initialize, projected
from .planning import snapshot, optimize, histories
from .forecasting import load_model, train

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app=FastAPI(title='Real records operations',lifespan=lifespan)
imports=Counter('real_records_imported_total','Changed real records',['kind'])
requests_count=Counter('real_records_http_requests_total','API responses',['method','route','status'])
request_latency=Histogram('real_records_http_request_seconds','API latency',['method','route'])
projection_pending=Gauge('real_records_projection_pending','Imported keys awaiting their current stream projection')
worker_seen=Gauge('real_records_worker_seen_timestamp','Last worker heartbeat timestamp',['service'])
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
provider=TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://otel:4318')+'/v1/traces')))
trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)

@app.middleware('http')
async def request_metrics(request:Request,call_next):
    started=time.perf_counter(); status=500
    try:
        response=await call_next(request);status=response.status_code;return response
    finally:
        route=getattr(request.scope.get('route'),'path','unmatched')
        requests_count.labels(request.method,route,str(status)).inc()
        request_latency.labels(request.method,route).observe(time.perf_counter()-started)

@app.middleware('http')
async def auth(request:Request,call_next):
    token=os.getenv('REAL_RECORDS_TOKEN','')
    if token and request.url.path not in {'/health','/metrics'}:
        import hmac
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Unauthorized'},status_code=401)
    return await call_next(request)

@app.exception_handler(ValueError)
async def invalid(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':str(exc)},status_code=400)

class Import(BaseModel):
    kind:str
    source:str=Field(min_length=1,max_length=120)
    records:list[dict]
    confirmed_real:bool=False

@app.get('/health')
def health():
    with db() as conn: conn.execute('SELECT 1')
    return {'status':'ok','workspace':'real_records','synthetic_data':False,'test_mode':os.getenv('REAL_RECORDS_TEST_MODE')=='1'}

@app.get('/metrics')
def metrics():
    with db() as conn:
        pending=conn.execute('SELECT count(*) AS n FROM records r LEFT JOIN projected p ON p.kind=r.kind AND p.id=r.id WHERE p.revision IS DISTINCT FROM r.revision').fetchone()['n']
        projection_pending.set(pending)
        for row in conn.execute('SELECT service,extract(epoch from updated_at) AS seen FROM heartbeat').fetchall():
            worker_seen.labels(row['service']).set(float(row['seen']))
    return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)

@app.get('/contracts')
def contracts(): return {k:v[0].split() for k,v in CONTRACTS.items()}

def preview(body):
    rows=validate_batch(body.kind,body.records,allow_synthetic=os.getenv('REAL_RECORDS_TEST_MODE')=='1')
    with db() as conn:
        existing={r['id']:r['hash'] for r in conn.execute('SELECT id,hash FROM records WHERE kind=%s',(body.kind,)).fetchall()}
    return rows,sum(existing.get(r['id'])!=record_hash(r) for r in rows)

@app.post('/validate')
def validate(body:Import):
    rows,changed=preview(body)
    return {'received':len(rows),'would_change':changed,'preview':rows[:8]}

@app.post('/imports')
def ingest(body:Import):
    if not body.confirmed_real: raise ValueError('Confirm the provenance of these records before importing')
    rows=validate_batch(body.kind,body.records,allow_synthetic=os.getenv('REAL_RECORDS_TEST_MODE')=='1'); changed=0
    with db() as conn:
        # Serialize import/proposal reservation to make version checks atomic.
        conn.execute('SELECT pg_advisory_xact_lock(876501)')
        active=conn.execute("SELECT 1 FROM proposals WHERE status IN ('RESERVED','REQUESTED') LIMIT 1").fetchone()
        if active: raise ValueError('Reconcile the outstanding dispatch request before importing a replacement snapshot')
        for row in rows:
            digest=record_hash(row)
            stored=conn.execute('''INSERT INTO records(kind,id,data,hash,source) VALUES (%s,%s,%s,%s,%s)
              ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data,hash=excluded.hash,source=excluded.source,
              revision=nextval('record_revision'),updated_at=now() WHERE records.hash<>excluded.hash RETURNING revision''',
              (body.kind,row['id'],Jsonb(row),digest,body.source)).fetchone()
            conn.execute('UPDATE records SET verified_at=now() WHERE kind=%s AND id=%s',(body.kind,row['id']))
            if stored:
                event={'id':str(uuid.uuid4()),'kind':body.kind,'record_id':row['id'],'revision':stored['revision'],'record':row,'source':body.source}
                conn.execute('INSERT INTO outbox(id,payload) VALUES (%s,%s)',(event['id'],Jsonb(event))); changed+=1
    imports.labels(body.kind).inc(changed)
    return {'received':len(rows),'changed':changed,'status':'QUEUED_FOR_CDC','workspace':'real_records'}

@app.get('/records')
def records(kind:str):
    if kind not in CONTRACTS: raise ValueError('Unknown record type')
    with db() as conn: return conn.execute('SELECT data,revision,source,updated_at FROM records WHERE kind=%s ORDER BY updated_at DESC LIMIT 200',(kind,)).fetchall()

def current():
    groups,version,imported=projected()
    return groups,snapshot(groups,version,imported,load_model())

@app.get('/state')
def state():
    groups,snap=current()
    with db() as conn:
        if snap['caught_up']:
            for row in snap['forecasts']:
                if not row['stale']:
                    conn.execute('''INSERT INTO forecast_predictions(sku,depot,target_date,data_version,forecast,source)
                      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                      (row['sku'],row['depot'],row['forecast_for'],snap['data_version'],row['daily'],row['source']))
        snap['proposals']=conn.execute('SELECT * FROM proposals ORDER BY created_at DESC LIMIT 30').fetchall()
        snap['models']=conn.execute('SELECT id,created_at,data_version,metrics,promoted,run_id FROM models ORDER BY created_at DESC LIMIT 5').fetchall()
        snap['requests']=conn.execute('SELECT * FROM dispatch_requests ORDER BY created_at DESC LIMIT 30').fetchall()
        snap['heartbeats']=conn.execute('SELECT * FROM heartbeat').fetchall()
        snap['quarantined']=conn.execute('SELECT count(*) AS n FROM quarantined').fetchone()['n']
    return snap

@app.get('/monitoring')
def forecast_outcomes():
    groups,_,_=projected(); actual=histories(groups)
    with db() as conn:
        rows=conn.execute('''SELECT DISTINCT ON (sku,depot,target_date) * FROM forecast_predictions
          ORDER BY sku,depot,target_date,created_at DESC''').fetchall()
    matched=[]
    for row in rows:
        observed=actual.get((row['sku'],row['depot']),{}).get(row['target_date'].isoformat())
        if observed is not None:
            matched.append({'sku':row['sku'],'depot':row['depot'],'date':row['target_date'].isoformat(),
                'forecast':row['forecast'],'requested':observed,'error':round(row['forecast']-observed,2),'source':row['source']})
    denominator=sum(r['requested'] for r in matched)
    return {'matched_days':len(matched),'wape':sum(abs(r['error']) for r in matched)/denominator if denominator else None,
            'rows':matched[-100:],'note':'Only forecasts saved before a subsequently imported target-day order observation can be matched. No actual outcomes are generated.'}

@app.post('/train')
def train_model(): return train()

class Scenario(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    days:int=Field(default=7,ge=1,le=30)
    demand_multiplier:float=Field(default=1,ge=0,le=5)
    delay_days:int=Field(default=0,ge=0,le=30)
    capacity_loss:float=Field(default=0,ge=0,le=1)

class Scenarios(BaseModel):
    scenarios:list[Scenario]=Field(min_length=1,max_length=24)

@app.post('/scenarios')
def scenarios(body:Scenarios):
    import ray
    _,snap=current()
    if not snap['forecasts']: raise ValueError('Import orders before comparing scenarios')
    if not ray.is_initialized(): ray.init(address=os.getenv('RAY_ADDRESS','ray://ray:10001'))
    task=ray.remote(scenario_metrics)
    return {'data_version':snap['data_version'],'engine':'Ray','results':ray.get([task.remote(snap,s.model_dump()) for s in body.scenarios],timeout=60)}

class PlanRequest(BaseModel):
    days:int=Field(default=7,ge=1,le=30)

@app.post('/optimize')
async def propose(body:PlanRequest):
    groups,snap=await asyncio.to_thread(current)
    result=await asyncio.to_thread(optimize,groups,snap,body.days)
    proposal_id=str(uuid.uuid4())
    with db() as conn:
        conn.execute('INSERT INTO proposals(id,data_version,plan) VALUES (%s,%s,%s)',(proposal_id,snap['data_version'],Jsonb(result)))
    # Workflow starts in WAITING FOR APPROVAL; failed starts can be retried by decide.
    from .workflows import ensure_workflow
    await ensure_workflow(proposal_id)
    return {'id':proposal_id,'status':'PENDING','plan':result}

class Decision(BaseModel):
    actor:str=Field(min_length=2,max_length=100)
    reason:str=Field(min_length=3,max_length=1000)
    approved:bool

@app.post('/proposals/{proposal_id}/decide')
async def decide(proposal_id:uuid.UUID,body:Decision):
    with db() as conn:
        row=conn.execute('SELECT status FROM proposals WHERE id=%s',(proposal_id,)).fetchone()
    if not row: raise HTTPException(404,'Proposal not found')
    if row['status']!='PENDING': raise HTTPException(409,'This proposal has already been decided')
    from .workflows import ensure_workflow, ApprovalWorkflow
    handle=await ensure_workflow(str(proposal_id))
    await handle.signal(ApprovalWorkflow.decide,body.model_dump())
    return {'id':str(proposal_id),'status':'DECISION_SENT','note':'Temporal records the decision and checks inventory version before reserving'}

class Reconcile(BaseModel):
    actor:str=Field(min_length=2,max_length=100)
    reason:str=Field(min_length=3,max_length=1000)

@app.post('/requests/{request_id}/reconcile')
def reconcile(request_id:uuid.UUID,body:Reconcile):
    with db() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(876501)')
        row=conn.execute("UPDATE dispatch_requests SET status='RECONCILED',reconciled_at=now(),payload=payload || %s WHERE id=%s AND status='AWAITING_ERP_ADAPTER' RETURNING id",(Jsonb({'reconciled_by':body.actor,'reconciliation':body.reason}),request_id)).fetchone()
        if not row: raise ValueError('No outstanding request with this ID')
        conn.execute("UPDATE proposals SET status='RECONCILED' WHERE id=%s",(request_id,))
        conn.execute('DELETE FROM reservations WHERE proposal_id=%s',(request_id,))
    return {'status':'RECONCILED','next':'Import fresh post-execution inventory snapshots before approving another plan'}

@app.get('/history')
def history():
    import clickhouse_connect
    client=clickhouse_connect.get_client(host=os.getenv('CLICKHOUSE_HOST','clickhouse'))
    rows=client.query('SELECT kind,count() FROM real_events FINAL GROUP BY kind').result_rows
    from .sinks import catalog
    table=catalog().load_table('operations.events')
    return {'clickhouse_counts':dict(rows),'iceberg_snapshot':table.current_snapshot().snapshot_id if table.current_snapshot() else None}

@app.get('/services')
async def services():
    checks={'FastAPI':'http://api:8000/health','Next.js / TypeScript / ECharts':'http://frontend:3000/operations/real',
      'Kafka / Debezium':'http://connect:8083/connectors/real-record-outbox/status','Apache Flink':'http://jobmanager:8081/jobs/overview',
      'S3 object storage':'http://objectstore:9333/cluster/status','ClickHouse':'http://clickhouse:8123/ping',
      'MLflow':'http://mlflow:5000/health','Airflow':'http://airflow:8080/health','Ray':'http://ray:8265/api/version',
      'Prometheus':'http://prometheus:9090/-/ready','Grafana':'http://grafana:3000/api/health','OpenTelemetry':'http://otel:13133/'}
    async with httpx.AsyncClient(timeout=3) as client:
        async def check(name,url):
            try:
                response=await client.get(url); response.raise_for_status()
                if name=='Kafka / Debezium':
                    data=response.json()
                    if data.get('connector',{}).get('state')!='RUNNING' or not data.get('tasks') or any(t.get('state')!='RUNNING' for t in data['tasks']): raise ValueError('Connector or task is not running')
                if name=='Apache Flink' and not any(j['state']=='RUNNING' for j in response.json().get('jobs',[])): raise ValueError('No running stream job')
                if name=='Airflow' and response.json().get('scheduler',{}).get('status')!='healthy': raise ValueError('Scheduler is not healthy')
                return {'name':name,'status':'UP'}
            except Exception as exc: return {'name':name,'status':'DOWN','detail':str(exc)[:180]}
        result=await asyncio.gather(*(check(n,u) for n,u in checks.items()))
    for name,fn in [('PostgreSQL',db_probe),('Redis',redis_probe)]:
        try: await asyncio.to_thread(fn); result.append({'name':name,'status':'UP'})
        except Exception as exc: result.append({'name':name,'status':'DOWN','detail':str(exc)[:180]})
    try:
        from temporalio.client import Client
        client=await Client.connect(os.getenv('TEMPORAL_ADDRESS','temporal:7233'))
        await client.service_client.check_health()
        result.append({'name':'Temporal','status':'UP'})
    except Exception as exc: result.append({'name':'Temporal','status':'DOWN','detail':str(exc)[:180]})
    def capabilities():
        from xgboost import XGBRegressor
        from ortools.linear_solver import pywraplp
        from .sinks import catalog
        table=catalog().load_table('operations.events')
        if not pywraplp.Solver.CreateSolver('SCIP'): raise RuntimeError('SCIP is unavailable')
        return [{'name':'Apache Iceberg','status':'UP','detail':'Catalog and event table readable'},
                {'name':'XGBoost / OR-Tools','status':'UP','detail':'Libraries available; train and optimize to exercise them'}]
    try: result.extend(await asyncio.to_thread(capabilities))
    except Exception as exc: result.append({'name':'Iceberg / model capabilities','status':'DOWN','detail':str(exc)[:180]})
    with db() as conn:
        workers=conn.execute("SELECT service,updated_at>now()-interval '45 seconds' AS current FROM heartbeat WHERE service IN ('projector','temporal-worker')").fetchall()
    seen={w['service']:w['current'] for w in workers}
    for name in ('projector','temporal-worker'):
        result.append({'name':name,'status':'UP' if seen.get(name) else 'DOWN','detail':'Recent worker heartbeat required'})
    return result

def db_probe():
    with db() as conn: return conn.execute('SELECT 1').fetchone()

def redis_probe():
    import redis
    return redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379'),socket_connect_timeout=2,socket_timeout=2).ping()
