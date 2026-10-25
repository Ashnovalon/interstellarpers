import json
import os
import tempfile
import uuid
from pathlib import Path
from .db import db, projected, heartbeat
from .planning import feature_rows
from psycopg.types.json import Jsonb

def load_model():
    from xgboost import XGBRegressor
    with db() as conn:
        row=conn.execute('SELECT * FROM models WHERE promoted ORDER BY created_at DESC LIMIT 1').fetchone()
    if not row: return None
    model=XGBRegressor()
    model.load_model(bytearray(row['artifact'],'utf-8'))
    return model

def train():
    import numpy as np
    import mlflow
    import mlflow.xgboost
    from xgboost import XGBRegressor
    groups,version,imported=projected()
    if version!=imported: raise ValueError('Wait for stream processing before training')
    rows=feature_rows(groups)
    dates=sorted({r[0] for r in rows})
    if len(dates)<28: raise ValueError('Need at least 35 consecutive dated order days (28 feature days) for training and held-out evaluation')
    cutoff=dates[-7]; training=[r for r in rows if r[0]<cutoff]; test=[r for r in rows if r[0]>=cutoff]
    model=XGBRegressor(n_estimators=80,max_depth=3,learning_rate=0.08,random_state=42,n_jobs=2)
    x=np.array([r[1] for r in training]); y=np.array([r[2] for r in training]); model.fit(x,y)
    tx=np.array([r[1] for r in test]); ty=np.array([r[2] for r in test]); pred=np.maximum(0,model.predict(tx))
    denominator=max(1,float(abs(ty).sum()))
    wape=float(abs(pred-ty).sum()/denominator); baseline=float(abs(tx[:,2]-ty).sum()/denominator)
    promoted=wape<=baseline
    mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI','http://mlflow:5000'))
    mlflow.set_experiment('real-record-demand')
    metrics={'wape':wape,'baseline_wape':baseline,'train_rows':len(training),'test_rows':len(test),
        'train_through':max(r[0] for r in training),'test_from':cutoff,'test_through':dates[-1]}
    with mlflow.start_run() as run:
        mlflow.log_params({'data_version':version,'source':'imported company orders','features':'lag1,lag7,mean7,weekday'})
        mlflow.log_metrics({k:v for k,v in metrics.items() if isinstance(v,(int,float))})
        mlflow.xgboost.log_model(model,'model',registered_model_name='real-record-demand')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.json'; model.save_model(path); artifact=path.read_text()
        with db() as conn:
            conn.execute('INSERT INTO models(id,data_version,artifact,metrics,promoted,run_id) VALUES (%s,%s,%s,%s,%s,%s)',
                (uuid.uuid4(),version,artifact,Jsonb(metrics),promoted,run.info.run_id))
    heartbeat('forecast',{'promoted':promoted,**metrics})
    return {'promoted':promoted,**metrics}
