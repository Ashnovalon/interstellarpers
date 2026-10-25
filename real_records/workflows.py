"""Durable human approval, atomic reservations, and idempotent local dispatch requests."""
import asyncio
import os
from datetime import timedelta
from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError, ApplicationError
from temporalio.worker import Worker

@workflow.defn
class ApprovalWorkflow:
    def __init__(self): self.decision=None

    @workflow.signal
    def decide(self,decision:dict):
        if self.decision is None: self.decision=decision

    @workflow.run
    async def run(self,proposal_id:str):
        await workflow.wait_condition(lambda:self.decision is not None)
        args={'id':proposal_id,**self.decision}
        result=await workflow.execute_activity(record_and_reserve,args,start_to_close_timeout=timedelta(seconds=30),
          retry_policy=RetryPolicy(maximum_attempts=5,non_retryable_error_types=['StaleProposal']))
        if result['status']=='RESERVED':
            return await workflow.execute_activity(create_dispatch,args,start_to_close_timeout=timedelta(seconds=30),retry_policy=RetryPolicy(maximum_attempts=5))
        return result

@activity.defn
async def record_and_reserve(args:dict): return await asyncio.to_thread(_reserve,args)

def _reserve(args):
    from .db import db
    from psycopg.types.json import Jsonb
    with db() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(876501)')
        row=conn.execute('SELECT * FROM proposals WHERE id=%s FOR UPDATE',(args['id'],)).fetchone()
        if not row: raise ApplicationError('Proposal missing',non_retryable=True)
        if row['status']!='PENDING': return {'status':row['status']}
        current=conn.execute('SELECT coalesce(max(revision),0) AS n FROM records').fetchone()['n']
        active=conn.execute("SELECT 1 FROM proposals WHERE status IN ('RESERVED','REQUESTED') LIMIT 1").fetchone()
        reconciled=conn.execute("SELECT reconciled_at FROM dispatch_requests WHERE status='RECONCILED' ORDER BY reconciled_at DESC LIMIT 1").fetchone()
        fresh_after_request=True
        if reconciled:
            # Every physical snapshot must have been replaced since the preceding request.
            fresh_after_request=not bool(conn.execute("SELECT 1 FROM records WHERE kind IN ('lot','material_lot','capacity','inbound','production','shipment') AND verified_at<=%s LIMIT 1",(reconciled['reconciled_at'],)).fetchone())
        stale=current!=row['data_version'] or bool(active) or not fresh_after_request
        status='STALE' if stale and args['approved'] else ('RESERVED' if args['approved'] else 'REJECTED')
        conn.execute('UPDATE proposals SET status=%s,actor=%s,reason=%s WHERE id=%s',(status,args['actor'],args['reason'],args['id']))
        if status=='RESERVED':
            conn.execute('INSERT INTO reservations(proposal_id,plan) VALUES (%s,%s) ON CONFLICT DO NOTHING',(args['id'],Jsonb(row['plan'])))
    return {'status':status}

@activity.defn
async def create_dispatch(args:dict): return await asyncio.to_thread(_dispatch,args)

def _dispatch(args):
    from .db import db
    from psycopg.types.json import Jsonb
    import uuid
    with db() as conn:
        row=conn.execute('SELECT * FROM proposals WHERE id=%s FOR UPDATE',(args['id'],)).fetchone()
        if row['status']=='REQUESTED': return {'status':'REQUESTED'}
        if row['status']!='RESERVED': raise ApplicationError('Reservation missing',non_retryable=True)
        payload={'proposal_id':args['id'],'plan':row['plan'],'actor':args['actor'],'reason':args['reason'],
                 'execution':'AWAITING_ERP_ADAPTER','physical_dispatch':False}
        conn.execute('INSERT INTO dispatch_requests(id,payload) VALUES (%s,%s) ON CONFLICT DO NOTHING',(args['id'],Jsonb(payload)))
        event={'id':str(uuid.uuid4()),'kind':'execution','record_id':args['id'],'revision':row['data_version'], 'record':payload,'source':'temporal'}
        conn.execute('INSERT INTO outbox(id,payload) VALUES (%s,%s)',(event['id'],Jsonb(event)))
        conn.execute("UPDATE proposals SET status='REQUESTED' WHERE id=%s",(args['id'],))
    return {'status':'REQUESTED','physical_dispatch':False}

async def ensure_workflow(proposal_id):
    client=await Client.connect(os.getenv('TEMPORAL_ADDRESS','temporal:7233'))
    workflow_id='real-record-plan-'+proposal_id
    try:
        return await client.start_workflow(ApprovalWorkflow.run,proposal_id,id=workflow_id,task_queue='real-record-decisions')
    except WorkflowAlreadyStartedError: return client.get_workflow_handle(workflow_id)

async def main():
    from .db import initialize, heartbeat
    initialize()
    client=await Client.connect(os.getenv('TEMPORAL_ADDRESS','temporal:7233'))
    async with Worker(client,task_queue='real-record-decisions',workflows=[ApprovalWorkflow],activities=[record_and_reserve,create_dispatch]):
        while True:
            await asyncio.to_thread(heartbeat,'temporal-worker')
            await asyncio.sleep(10)

if __name__=='__main__': asyncio.run(main())
