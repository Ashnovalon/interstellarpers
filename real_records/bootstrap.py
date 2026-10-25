"""Register the CDC connector; safe to run again."""
import os
import time
import httpx
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from .db import initialize

def main():
    initialize()
    admin=KafkaAdminClient(bootstrap_servers='kafka:9092',api_version=(2,6,0))
    try:
        for topic in ('real.public.outbox','real.validated'):
            try: admin.create_topics([NewTopic(topic,num_partitions=1,replication_factor=1)])
            except TopicAlreadyExistsError: pass
    finally: admin.close()
    config={'connector.class':'io.debezium.connector.postgresql.PostgresConnector','database.hostname':'postgres',
      'database.port':'5432','database.user':'real','database.password':os.environ['POSTGRES_PASSWORD'],
      'database.dbname':'real_records','topic.prefix':'real','plugin.name':'pgoutput','slot.name':'real_record_outbox',
      'publication.name':'real_record_publication','publication.autocreate.mode':'filtered','table.include.list':'public.outbox',
      'snapshot.mode':'initial','tombstones.on.delete':'false','key.converter':'org.apache.kafka.connect.json.JsonConverter',
      'key.converter.schemas.enable':'false','value.converter':'org.apache.kafka.connect.json.JsonConverter','value.converter.schemas.enable':'false'}
    for attempt in range(60):
        try:
            r=httpx.put('http://connect:8083/connectors/real-record-outbox/config',json=config,timeout=10); r.raise_for_status()
            print('Real-record CDC registered',flush=True); return
        except httpx.HTTPError:
            if attempt==59: raise
            time.sleep(3)

if __name__=='__main__': main()
