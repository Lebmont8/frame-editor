import json,os,secrets,socket,subprocess,sys,tempfile,time,unittest,urllib.request
from pathlib import Path

@unittest.skipUnless(os.environ.get("FRAME_TEST_ENGINE"),"Set FRAME_TEST_ENGINE to a separately obtained FilmCraft executable")
class WorkerSmokeTest(unittest.TestCase):
    def test_real_engine_worker_starts_and_serves_a_new_project(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="frame-public-worker-") as d:
            sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1];sock.close()
            origin="http://127.0.0.1:"+str(port);token=secrets.token_hex(32)
            env={**os.environ,"FRAME_ENGINE":os.environ["FRAME_TEST_ENGINE"],"FRAME_LOCAL_ORIGIN":origin,"FRAME_WORKER_TOKEN":token,"FRAME_NATIVE_PORT":"1","FRAME_NATIVE_TOKEN":"synthetic-offline-test","PYTHONDONTWRITEBYTECODE":"1"}
            p=subprocess.Popen([sys.executable,"-B",str(root/"desktop/runtime/server.py"),"--port",str(port),"--data",d],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                def read(route):
                    req=urllib.request.Request(origin+"/youtube-hub/frame"+route,headers={"X-Frame-Worker-Token":token,"Origin":origin})
                    with urllib.request.urlopen(req,timeout=2) as r:return json.load(r)
                health=None
                for _ in range(60):
                    if p.poll() is not None:break
                    try:health=read("/health");break
                    except Exception:time.sleep(.25)
                if health is None:self.fail("Public worker did not start: "+(p.stderr.read(2000)if p.poll()is not None else"startup timeout"))
                self.assertEqual(health["status"],"ok")
                state=read("/api/state")
                self.assertIn("document",state);self.assertTrue(state["project"].endswith(".fcproj"))
            finally:
                p.terminate()
                try:p.communicate(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=5)

if __name__=="__main__":unittest.main()
