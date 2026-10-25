import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from server import AppServer

class RealProxyTests(unittest.TestCase):
    def test_unavailable_real_stack_returns_explained_503_and_keeps_live_api(self):
        app=AppServer(('127.0.0.1',0),':memory:')
        thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{app.server_port}'
        try:
            before=app.live.snapshot()['run_id']
            with patch('server.urlopen',side_effect=URLError('offline')):
                for path,body,expected in [('/operations/real',None,b'services are currently offline'),
                  ('/operations/real/api/state',None,b'Real-records services are offline'),
                  ('/operations/real/api/imports',b'{}',b'Real-records services are offline')]:
                    with self.subTest(path=path),self.assertRaises(HTTPError) as caught:
                        urlopen(Request(base+path,data=body,headers={'Content-Type':'application/json'}))
                    self.assertEqual(caught.exception.code,503)
                    self.assertIn(expected,caught.exception.read())
            with urlopen(base+'/api/live/state') as response:
                self.assertEqual(response.status,200)
            with urlopen(base+'/operations') as response:
                self.assertIn(b'Import real records',response.read())
            self.assertEqual(before,app.live.snapshot()['run_id'])
        finally:
            app.shutdown();app.server_close();thread.join(5)

if __name__=='__main__': unittest.main()
