import json
import os
from pyflink.common import Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.functions import KeyedProcessFunction
from pyflink.datastream.state import MapStateDescriptor, ValueStateDescriptor
from pyflink.datastream.checkpoint_storage import FileSystemCheckpointStorage
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaOffsetsInitializer, KafkaSink, KafkaRecordSerializationSchema
from pyflink.datastream.connectors.base import DeliveryGuarantee
from real_records.contracts import validate_record

def unwrap(raw):
    envelope=json.loads(raw)
    body=envelope.get('payload',envelope)
    after=body.get('after') if isinstance(body,dict) else None
    if not after: return ''
    event=after['payload']
    return event if isinstance(event,str) else json.dumps(event)

class LiveState(KeyedProcessFunction):
    def open(self,context):
        self.rows=context.get_map_state(MapStateDescriptor('record-versions',Types.STRING(),Types.STRING()))
        self.total=context.get_state(ValueStateDescriptor('quantity',Types.DOUBLE()))

    def process_element(self,value,ctx):
        event=json.loads(value)
        try:
            if event['kind']!='execution': validate_record(event['kind'],event['record'],allow_synthetic=os.getenv('REAL_RECORDS_TEST_MODE')=='1')
            old=self.rows.get(event['record_id'])
            old=json.loads(old) if old else None
            if old and old['revision']>=event['revision']: return
            quantity=lambda r:float(r.get('quantity',r.get('quantity_kg',0)))
            total=(self.total.value() or 0)- (quantity(old['record']) if old else 0)+quantity(event['record'])
            self.rows.put(event['record_id'],json.dumps(event)); self.total.update(total)
            event['validation']='VALID'; event['live_quantity']=total
            r=event['record']
            event['disruption']=event['kind']=='route' and r.get('status') in {'WATCH','CONFIRMED_CLOSED'} or event['kind']=='capacity' and r.get('status') in {'DOWN','REDUCED'}
        except (ValueError,KeyError,TypeError) as exc:
            event['validation']='INVALID'; event['error']=str(exc)
        yield json.dumps(event)

def main():
    env=StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1); env.enable_checkpointing(10000)
    env.get_checkpoint_config().set_checkpoint_storage(FileSystemCheckpointStorage('file:///checkpoints'))
    source=(KafkaSource.builder().set_bootstrap_servers('kafka:9092').set_topics('real.public.outbox')
      .set_group_id('real-record-flink').set_starting_offsets(KafkaOffsetsInitializer.earliest())
      .set_value_only_deserializer(SimpleStringSchema()).build())
    stream=env.from_source(source,WatermarkStrategy.no_watermarks(),'Debezium outbox').map(unwrap,output_type=Types.STRING()).filter(lambda x:bool(x))
    processed=stream.key_by(lambda raw:json.loads(raw)['kind'],key_type=Types.STRING()).process(LiveState(),output_type=Types.STRING())
    sink=(KafkaSink.builder().set_bootstrap_servers('kafka:9092')
      .set_record_serializer(KafkaRecordSerializationSchema.builder().set_topic('real.validated').set_value_serialization_schema(SimpleStringSchema()).build())
      .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE).build())
    processed.sink_to(sink); env.execute('Real records validation and live state')

if __name__=='__main__': main()
