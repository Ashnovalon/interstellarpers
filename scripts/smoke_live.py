"""Verify a running local app pushes independent one-second business ticks.

Temporarily advances the active synthetic run; preserves its previous running state.
"""
import argparse
import json
import os
import time
from urllib.request import Request,urlopen

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--url",default="http://127.0.0.1:8765")
    args=parser.parse_args();root=args.url.rstrip('/')
    headers={"Authorization":"Bearer "+os.environ["CONTROL_TOWER_TOKEN"]} if os.getenv("CONTROL_TOWER_TOKEN") else {}
    def request(path,body=None):
        h=dict(headers)
        if body is not None:h['Content-Type']='application/json'
        with urlopen(Request(root+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=20) as response:
            return json.loads(response.read())
    before=request('/api/live/state');was_running=before['running']
    if before['day']>=111:raise SystemExit('Create a fresh run before the real-time smoke test')
    stream=urlopen(Request(root+'/api/live/stream',headers=headers),timeout=8)
    def snapshot():
        while True:
            line=stream.readline()
            if not line:raise RuntimeError('SSE closed unexpectedly')
            if line.startswith(b'data: '):return json.loads(line[6:])
    try:
        initial=snapshot();start=time.monotonic()
        if not was_running:request('/api/live/control',{'action':'start'})
        seen=set()
        while len(seen)<3:
            current=snapshot()
            if current['tick']>initial['tick']:seen.add(current['tick'])
            assert current['metrics']['bottle_conservation_error']==0
        elapsed=time.monotonic()-start
        assert elapsed<6, f'Push updates are too slow: {elapsed:.2f}s'
        if not was_running:request('/api/live/control',{'action':'pause'})
        current=request('/api/live/state')
        offer=next(iter(current['actions']),None)
        if offer:
            comparison=request('/api/live/compare',{'id':offer['id'],'version':offer['version']})
            assert len(comparison['branches'])>=3
        events=request('/api/live/events')
        batches=[e for e in events['events'] if e['kind']=='TICK']
        assert len(batches[-1]['payload']['detail']['order_batches'])==135
        print(json.dumps({'status':'PASS','pushed_ticks':len(seen),'wall_seconds':round(elapsed,2),
            'business_day':current['day'],'model_series':current['model']['positions'],
            'order_series_per_tick':135,'stock_positions':len(current['positions']),
            'conservation_error':current['metrics']['bottle_conservation_error'],'recommendations':len(current['actions'])},indent=2))
    finally:
        stream.close()
        if not was_running:request('/api/live/control',{'action':'pause'})

if __name__=='__main__':main()
