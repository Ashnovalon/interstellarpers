import json
import os
import time
import logging
from kafka import KafkaConsumer
from psycopg.types.json import Jsonb
import redis
from .db import db, initialize, heartbeat
from .sinks import clients, archive

log=logging.getLogger('real-record-projector')

def project(event,cache):
    with db() as conn:
        new=conn.execute('INSERT INTO processed_events(id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id',(event['id'],)).fetchone()
        if new:
            if event.get('validation')!='VALID':
                conn.execute('INSERT INTO quarantined(id,error,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(event['id'],event.get('error','invalid event'),Jsonb(event)))
            elif event['kind']!='execution':
                conn.execute('''INSERT INTO projected(kind,id,data,revision) VALUES (%s,%s,%s,%s)
                  ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data,revision=excluded.revision WHERE projected.revision<excluded.revision''',
                  (event['kind'],event['record_id'],Jsonb(event['record']),event['revision']))
    # Projection is authoritative. Cache can be reconstructed and never governs approval.
    cache.set('real:last-event',json.dumps(event),ex=300)
    heartbeat('projector',{'event_id':event['id'],'revision':event['revision'],'validation':event.get('validation')})

def main():
    logging.basicConfig(level=logging.INFO)
    initialize()
    consumer=KafkaConsumer('real.validated',bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP','kafka:9092'),
      group_id='real-record-projector',auto_offset_reset='earliest',enable_auto_commit=False,
      value_deserializer=lambda b:json.loads(b),max_poll_records=1,max_poll_interval_ms=600000)
    cache=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379'))
    s3,cat,ch=clients()
    while True:
        batch=consumer.poll(timeout_ms=1000,max_records=1)
        for messages in batch.values():
            for message in messages:
                # Retry this event before polling later offsets: never skip a failed sink.
                while True:
                    try:
                        archive(message.value,s3,cat,ch)
                        project(message.value,cache)
                        consumer.commit(); break
                    except Exception:
                        log.exception('Event processing failed; retaining Kafka offset')
                        time.sleep(5)
        heartbeat('projector')

if __name__=='__main__': main()
