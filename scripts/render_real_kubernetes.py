"""Render the same local stack to Kubernetes, including every worker and config.

Requires PyYAML. Run from any directory; no cluster is contacted.
"""
import json
import os
from pathlib import Path
import re
import yaml

ROOT=Path(__file__).resolve().parents[1]
STACK=ROOT/'real_records'
NAMESPACE='pulp-real-records'
PORTS={'postgres':[5432],'redis':[6379],'kafka':[9092],'connect':[8083],'jobmanager':[8081,6123,6124],
 'taskmanager':[6121,6122],'objectstore':[9000,9333,19333,8888,18888,8080,18080],'clickhouse':[8123,9000],'api':[8000],
 'temporal':[7233,8233],'ray':[10001,8265],'mlflow':[5000],'airflow':[8080],'frontend':[3000],
 'otel':[4318,8889,13133],'prometheus':[9090],'grafana':[3000]}

def resolve(value):
    if isinstance(value,str):
        return re.sub(r'\$\{(\w+)(?::-([^}]*))?\}',lambda m:os.getenv(m[1],m[2] or ''),value)
    if isinstance(value,dict): return {k:resolve(v) for k,v in value.items()}
    if isinstance(value,list): return [resolve(v) for v in value]
    return value

def render():
    compose=resolve(yaml.safe_load((STACK/'compose.yaml').read_text()))
    objects=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':NAMESPACE}}]
    def obj(kind,name,spec,api='v1'):
        return {'apiVersion':api,'kind':kind,'metadata':{'name':name,'namespace':NAMESPACE},**spec}
    for name in compose['volumes']:
        objects.append(obj('PersistentVolumeClaim',name,{'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'2Gi'}}}}))
    for name,service in compose['services'].items():
        labels={'app':name}
        image=service.get('image') or ('pulp-real-frontend:local' if name=='frontend' else 'pulp-real-flink:local' if 'flink/Dockerfile' in service.get('build',{}).get('dockerfile','') else 'pulp-real-api:local')
        container={'name':name,'image':image,'imagePullPolicy':'IfNotPresent'}
        if 'user' in service: container['securityContext']={'runAsUser':int(service['user'].split(':')[0])}
        if 'mem_limit' in service:
            memory=service['mem_limit'].replace('m','Mi').replace('g','Gi')
            container['resources']={'limits':{'memory':memory}}
        if 'environment' in service:
            # Local development values only. Move credentials to managed Secrets for a shared cluster.
            container['env']=[{'name':str(k),'value':str(v)} for k,v in service['environment'].items()]
        if 'command' in service:
            container['args']=service['command'] if isinstance(service['command'],list) else service['command'].split()
        if 'entrypoint' in service: container['command']=service['entrypoint']
        mounts=[];volumes=[]
        for index,mount in enumerate(service.get('volumes',[])):
            source,target,*mode=mount.split(':')
            volume_name=f'volume-{index}'
            if source in compose['volumes']:
                volumes.append({'name':volume_name,'persistentVolumeClaim':{'claimName':source}})
                mounts.append({'name':volume_name,'mountPath':target})
            else:
                path=(STACK/source).resolve()
                paths=list(path.rglob('*')) if path.is_dir() else [path]
                data={};items=[]
                for i,p in enumerate(p for p in paths if p.is_file() and '__pycache__' not in str(p) and p.suffix!='.pyc'):
                    key='file-'+str(i); data[key]=p.read_text(encoding='utf-8')
                    subpath=p.relative_to(path).as_posix() if path.is_dir() else p.name
                    items.append({'key':key,'path':subpath})
                config_name=name+'-config-'+str(index)
                objects.append(obj('ConfigMap',config_name,{'data':data}))
                volumes.append({'name':volume_name,'configMap':{'name':config_name,'items':items}})
                entry={'name':volume_name,'mountPath':target,'readOnly':True}
                if not path.is_dir(): entry['subPath']=path.name
                mounts.append(entry)
        if name=='ray':
            volumes.append({'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'1Gi'}})
            mounts.append({'name':'shm','mountPath':'/dev/shm'})
        if mounts: container['volumeMounts']=mounts
        if name=='api':
            container['readinessProbe']={'httpGet':{'path':'/health','port':8000},'initialDelaySeconds':10,'periodSeconds':10}
        if name=='frontend':
            container['readinessProbe']={'httpGet':{'path':'/operations/real','port':3000},'initialDelaySeconds':10,'periodSeconds':10}
        pod={'containers':[container],'volumes':volumes}
        fs_groups={'jobmanager':999,'taskmanager':999,'kafka':1000,'airflow':0,'grafana':472,'prometheus':65534}
        if name in fs_groups: pod['securityContext']={'fsGroup':fs_groups[name]}
        template={'metadata':{'labels':labels},'spec':pod}
        if name in {'bootstrap','flink-submit'}:
            pod['restartPolicy']='OnFailure'
            objects.append(obj('Job',name,{'spec':{'backoffLimit':30,'template':template}},'batch/v1'))
        else:
            objects.append(obj('Deployment',name,{'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':labels},'template':template}},'apps/v1'))
        if name in PORTS:
            objects.append(obj('Service',name,{'spec':{'selector':labels,'ports':[{'name':'p'+str(p),'port':p,'targetPort':p} for p in PORTS[name]]}}))
    dest=STACK/'kubernetes.yaml'
    dest.write_text('# Generated by scripts/render_real_kubernetes.py; local development only.\n'+yaml.safe_dump_all(objects,sort_keys=False),encoding='utf-8')
    print(f'Rendered {len(objects)} objects for {len(compose["services"])} services to {dest}')

if __name__=='__main__': render()
