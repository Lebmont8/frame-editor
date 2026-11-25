"""Fetch pinned public runtime bundles; all outputs remain in isolated desktop tree."""
import urllib.request,json,pathlib,hashlib,tarfile,zipfile,subprocess,os
R=pathlib.Path(__file__).resolve().parent;V=R/'vendor';C=R/'build-cache';C.mkdir(exist_ok=True);manifest=[]
def get(url,name,digest=None):
 p=C/name
 if not p.exists():
  print('fetch',name,flush=True)
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Frame-build/0.1'}),timeout=90)as src,p.open('wb')as out:
   while b:=src.read(1024**2):out.write(b)
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if digest and digest.startswith('sha256:')and h!=digest.split(':')[1]:raise ValueError('Vendor SHA mismatch:'+name)
 manifest.append({'name':name,'url':url,'sha256':h,'bytes':p.stat().st_size});return p
def api(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Frame-build/0.1'}),timeout=30)as r:return json.load(r)
fc=api('https://api.github.com/repos/storytold/filmcraft/releases/tags/v0.20.1');py=api('https://api.github.com/repos/astral-sh/python-build-standalone/releases/tags/20261123')
for osname,arch,pymatch,fcname in [
 ('win','x64','cpython-3.12.16+20261123-x86_64-pc-windows-msvc-install_only_stripped.tar.gz','filmcraft-0.20.1-windows-x64-portable.zip'),
 ('mac','arm64','cpython-3.12.16+20261123-aarch64-apple-darwin-install_only_stripped.tar.gz','filmcraft-cli-0.20.1-macos-universal.zip')]:
 dest=V/(osname+'-'+arch);dest.mkdir(parents=True,exist_ok=True)
 a=next(a for a in py['assets']if a['name']==pymatch);p=get(a['browser_download_url'],pymatch,a.get('digest'))
 with tarfile.open(p)as t:t.extractall(dest,filter='data')
 a=next(a for a in fc['assets']if a['name']==fcname);p=get(a['browser_download_url'],fcname,a.get('digest'))
 engine=dest/'engine';engine.mkdir(exist_ok=True)
 with zipfile.ZipFile(p)as z:
  for n in z.namelist():
   if n.endswith('/')or not ('filmcraft-cli'in n or n.endswith(('.dll','.dylib','.so'))):continue
   target=engine/pathlib.PurePosixPath(n).name;target.write_bytes(z.read(n));target.chmod(0o755)
 bins=dest/'bin';bins.mkdir(exist_ok=True)
 target='win32-x64'if osname=='win'else'darwin-arm64'
 for tool in ['ffmpeg','ffprobe']:
  p=get('https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/'+tool+'-'+target,tool+'-'+target)
  b=bins/(tool+('.exe'if osname=='win'else''));__import__('shutil').copyfile(p,b);b.chmod(0o755)
 site=dest/'python'/('Lib/site-packages'if osname=='win'else'lib/python3.12/site-packages');site.mkdir(parents=True,exist_ok=True)
 wh=C/('wheels-'+osname);wh.mkdir(exist_ok=True)
 targetWheel='win_amd64.whl'if osname=='win'else'macosx_11_0_arm64.whl'
 meta=api('https://pypi.org/pypi/numpy/2.2.6/json')
 wheel=next(f for f in meta['urls']if 'cp312-cp312'in f['filename']and f['filename'].endswith(targetWheel))
 wp=get(wheel['url'],wheel['filename'],'sha256:'+wheel['digests']['sha256'])
 __import__('shutil').copyfile(wp,wh/wp.name)
 for w in wh.glob('*.whl'):
  with zipfile.ZipFile(w)as z:z.extractall(site)
 font=dest/'fonts';font.mkdir(exist_ok=True);__import__('shutil').copy('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',font/'DejaVuSans-Bold.ttf')
 print('READY',osname,flush=True)
(R/'acceptance-397/vendor-manifest.json').write_text(json.dumps(manifest,indent=2))

