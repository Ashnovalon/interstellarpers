from datetime import datetime, timedelta
import json
import os
from urllib.request import Request,urlopen
from airflow import DAG
from airflow.operators.python import PythonOperator

def retrain():
    headers={'Content-Type':'application/json'}
    token=os.getenv('REAL_RECORDS_TOKEN','')
    if token: headers['Authorization']='Bearer '+token
    req=Request('http://api:8000/train',data=b'{}',headers=headers,method='POST')
    try:
        with urlopen(req,timeout=300) as response: print(json.load(response))
    except Exception as exc:
        # Insufficient history is a visible skipped training run, never synthetic fill.
        if getattr(exc,'code',None)==400:
            from airflow.exceptions import AirflowSkipException
            raise AirflowSkipException(exc.read().decode())
        raise

with DAG('real_record_demand_training',start_date=datetime(2026,1,1),schedule='@daily',catchup=False,
         default_args={'retries':2,'retry_delay':timedelta(minutes=5)},tags=['real-records']) as dag:
    PythonOperator(task_id='train_evaluate_version',python_callable=retrain)
