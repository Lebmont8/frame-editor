"""Frame-owned staged updater. Never touches workspaces, media, login or models."""
import ctypes,hashlib,json,os,pathlib,plistlib,re,shutil,stat,subprocess,sys,time,zipfile
P=pathlib.Path
def atomic(p,v):
 p=P(p);t=p.with_suffix(p.suffix+".new")
 with t.open("w",encoding="utf-8")as f:
  json.dump(v,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def digest(p):
 h=hashlib.sha256()
 with P(p).open("rb")as f:
  while b:=f.read(1024**2):h.update(b)
 return h.hexdigest()
def private_tree(p):
 if p.is_symlink():raise ValueError("Symlink installation path")
 return p.resolve(strict=True)
def safe_extract(archive,destination,max_bytes,max_files):
 """Validate names/types/link targets before extraction; create links last."""
 destination=P(destination)
 if destination.exists():raise ValueError("Staging directory already exists")
 with zipfile.ZipFile(archive)as z:
  entries=z.infolist();seen=set();links=set();total=0
  if len(entries)>max_files:raise ValueError("Too many archive entries")
  for e in entries:
   name=e.filename;p=pathlib.PurePosixPath(name)
   if not name or "\\"in name or "\x00"in name or p.is_absolute()or ".."in p.parts or p.parts[0]!="Frame.app"or ":"in name or p.as_posix().rstrip("/")!=name.rstrip("/"):raise ValueError("Unsafe archive name")
   if p.as_posix()in seen:raise ValueError("Duplicate archive name")
   seen.add(p.as_posix());mode=e.external_attr>>16;kind=stat.S_IFMT(mode)
   if kind not in [0,stat.S_IFREG,stat.S_IFDIR,stat.S_IFLNK]:raise ValueError("Unsafe archive type")
   total+=e.file_size
   if total>max_bytes:raise ValueError("Archive expanded size exceeded")
   if stat.S_ISLNK(mode):
    if e.file_size>4096:raise ValueError("Oversized symlink")
    link=z.read(e).decode("utf-8");target=pathlib.PurePosixPath(link)
    if target.is_absolute()or "\\"in link or ":"in link:raise ValueError("Unsafe symlink")
    normalized=os.path.normpath(str(p.parent/target))
    if not normalized.startswith("Frame.app/"):raise ValueError("Escaping symlink")
    links.add(p)
  for e in entries:
   p=pathlib.PurePosixPath(e.filename)
   if any(parent in links for parent in p.parents):raise ValueError("Write through archive symlink")
  destination.mkdir(mode=0o700)
  for e in entries:
   p=destination/e.filename;mode=e.external_attr>>16
   if stat.S_ISLNK(mode):continue
   if e.is_dir():p.mkdir(parents=True,exist_ok=True);continue
   p.parent.mkdir(parents=True,exist_ok=True)
   with z.open(e)as src,p.open("xb")as dst:shutil.copyfileobj(src,dst,1024**2)
   p.chmod((mode&0o777)or 0o644)
  for e in entries:
   if stat.S_ISLNK(e.external_attr>>16):os.symlink(z.read(e).decode("utf-8"),destination/e.filename)
 app=destination/"Frame.app"
 with(app/"Contents/Info.plist").open("rb")as f:info=plistlib.load(f)
 if info.get("CFBundleIdentifier")!="com.vexora.frame":raise ValueError("Wrong app identifier")
 if not(app/"Contents/MacOS/Frame").is_file():raise ValueError("Missing executable")
 return app
def capacity(groups,reserve=True):
 """Group simultaneous allocations by actual filesystem."""
 out={}
 for p,extra in groups:
  p=private_tree(P(p));dev=p.stat().st_dev
  if dev not in out:
   u=shutil.disk_usage(p);out[dev]={"free":u.free,"total":u.total,"bytes":0}
  out[dev]["bytes"]+=int(extra)
 for v in out.values():
  v["required"]=v["bytes"]+(max(5*1024**3,int(v["total"]*.1))if reserve else 0)
  if v["free"]<v["required"]:raise ValueError("Недостаточно места для безопасного обновления")
 return list(out.values())
def configuration(plan):
 d=json.loads(P(plan).read_text("utf-8"))
 root=private_tree(P(d["cache"]));target=private_tree(P(d["target"]));artifact=private_tree(P(d["artifact"]))
 if not re.fullmatch(r"[a-f0-9]{32}",d["nonce"])or root.name!="update-"+d["nonce"]:raise ValueError("Invalid update identity")
 if not artifact.is_relative_to(root)or not P(plan).resolve().is_relative_to(root):raise ValueError("Invalid update path")
 if root==target or root.is_relative_to(target)or target.is_relative_to(root):raise ValueError("Overlapping update paths")
 if d["platform"]not in ["windows","mac"]:raise ValueError("Invalid platform")
 if d["platform"]=="windows":
  if not(target/".vexora-frame-install").is_file()or not(target/"Frame.exe").is_file():raise ValueError("Not a Frame installation")
 else:
  if target.suffix!=".app":raise ValueError("Not an app bundle")
  with(target/"Contents/Info.plist").open("rb")as f:info=plistlib.load(f)
  if info.get("CFBundleIdentifier")!="com.vexora.frame":raise ValueError("Wrong app")
 if artifact.stat().st_size!=d["bytes"]or digest(artifact)!=d["sha256"]:raise ValueError("Package SHA mismatch")
 if not re.fullmatch(r"\d+\.\d+\.\d+",d["version"]):raise ValueError("Invalid version")
 return d,root,target,artifact
def prepare(plan):
 d,root,target,artifact=configuration(plan)
 capacity([(root,d["helperBytes"]+16*1024**2),(target.parent,d["installBytes"]+16*1024**2)])
 if d["platform"]=="mac":
  staged=safe_extract(artifact,root/"unpack",d["installBytes"],d["fileCount"])
  with(staged/"Contents/Info.plist").open("rb")as f:info=plistlib.load(f)
  if info.get("CFBundleShortVersionString")!=d["version"]:raise ValueError("Wrong staged version")
  candidate=target.parent/(".Frame-update-"+d["nonce"]+".app")
  if candidate.exists():raise ValueError("Candidate collision")
  if staged.stat().st_dev==target.parent.stat().st_dev:os.replace(staged,candidate)
  else:
   capacity([(target.parent,d["installBytes"]+16*1024**2)])
   shutil.copytree(staged,candidate,symlinks=True)
  atomic(root/"candidate.json",{"path":str(candidate)})
 print(json.dumps({"prepared":True}),flush=True)
def parent_waiter(pid):
 if sys.platform=="win32":
  from ctypes import wintypes
  k=ctypes.WinDLL("kernel32",use_last_error=True)
  k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
  k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD
  k.CloseHandle.argtypes=[wintypes.HANDLE]
  h=k.OpenProcess(0x00100000,False,pid)
  if not h:raise RuntimeError("Cannot bind parent process")
  def wait():
   try:
    if k.WaitForSingleObject(h,120000)!=0:raise RuntimeError("Frame did not exit")
   finally:k.CloseHandle(h)
  return wait
 if pid<=1:raise ValueError("Invalid parent")
 def wait():
  end=time.monotonic()+120
  while time.monotonic()<end:
   try:os.kill(pid,0)
   except ProcessLookupError:return
   time.sleep(.2)
  raise RuntimeError("Frame did not exit")
 return wait
def launch(target,d,receipt=True):
 exe=target/("Frame.exe"if d["platform"]=="windows"else"Contents/MacOS/Frame")
 env={k:v for k,v in os.environ.items()if not k.startswith("FRAME_UPDATE_")}
 args=[str(exe)]
 if receipt:args+=["--frame-update-receipt="+str(P(d["cache"])/"boot.json"),"--frame-update-nonce="+d["nonce"]]
 return subprocess.Popen(args,cwd=str(target.parent),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**({"creationflags":0x00000008|0x00000200}if sys.platform=="win32"else{"start_new_session":True}))
def prune_previous(root,target,keep):
 """Retain latest rollback; prune only exact managed application trees and own cache."""
 for prior in root.parent.glob("update-*"):
  if prior==root or prior.is_symlink()or not re.fullmatch(r"update-[a-f0-9]{32}",prior.name):continue
  try:
   state=json.loads((prior/"status.json").read_text())
   if state.get("phase")not in ["complete","rolled-back"]:continue
   if state.get("target")!=str(target):continue
   if state["phase"]=="complete":
    nonce=prior.name[7:];backup=target.parent/(".Frame-previous-"+nonce+(".app"if target.suffix==".app"else""))
    if backup==keep or str(backup)!=state.get("backup")or backup.is_symlink():continue
    if backup.exists():
     manifest=backup/("Contents/Resources/frame-managed-files.json"if target.suffix==".app"else"resources/frame-managed-files.json")
     managed=json.loads(manifest.read_text());actual={p.relative_to(backup).as_posix()for p in backup.rglob("*")if p.is_file()or p.is_symlink()}
     expected=set(managed["files"])
     if target.suffix!=".app":expected|={".vexora-frame-install","Uninstall.exe"}
     if managed.get("appId")!="com.vexora.frame"or actual!=expected:continue
     shutil.rmtree(backup)
   for name in ["package.exe","package.zip","helper-python","unpack","update_helper.py"]:
    p=prior/name
    if p.is_symlink()or p.is_file():p.unlink()
    elif p.is_dir():shutil.rmtree(p)
  except (OSError,ValueError,KeyError):continue
def swap(d,root,target,artifact,wait,install=None,start=launch,timeout=90):
 """Inject OS actions to test failure/recovery without a native device."""
 backup=target.parent/(".Frame-previous-"+d["nonce"]+(".app"if d["platform"]=="mac"else""))
 if backup.exists():raise ValueError("Backup collision")
 wait()
 end=time.monotonic()+30
 while True:
  try:os.replace(target,backup);break
  except PermissionError:
   if time.monotonic()>=end:raise
   time.sleep(.25)
 child=None
 atomic(root/"status.json",{"phase":"replacing","target":str(target),"backup":str(backup),"nonce":d["nonce"]})
 try:
  if d["platform"]=="mac":
   candidate=P(json.loads((root/"candidate.json").read_text())["path"])
   if candidate!=target.parent/(".Frame-update-"+d["nonce"]+".app")or candidate.is_symlink():raise ValueError("Invalid candidate")
   os.replace(candidate,target)
  elif install:install(target)
  else:
   command='"'+str(artifact)+'" /S /D='+str(target)
   result=subprocess.run(command,timeout=300,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   if result.returncode or not(target/"Frame.exe").is_file():raise RuntimeError("Installer did not complete")
  child=start(target,d)
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   try:
    boot=json.loads((root/"boot.json").read_text())
    if boot.get("nonce")==d["nonce"]and boot.get("version")==d["version"]and boot.get("pid")==child.pid:
     atomic(root/"status.json",{"phase":"complete","target":str(target),"backup":str(backup),"nonce":d["nonce"],"version":d["version"]});prune_previous(root,target,backup);return True
   except(FileNotFoundError,ValueError):pass
   if child.poll()is not None:break
   time.sleep(.25)
  raise RuntimeError("New Frame failed startup acceptance")
 except Exception:
  if child and child.poll()is None:
   child.terminate()
   try:child.wait(timeout=15)
   except subprocess.TimeoutExpired:
    atomic(root/"status.json",{"phase":"blocked-running-candidate","target":str(target),"backup":str(backup)});raise
  if target.exists():
   failed=target.parent/(".Frame-failed-"+d["nonce"]+(".app"if d["platform"]=="mac"else""))
   if failed.exists():raise RuntimeError("Recovery destination occupied")
   os.replace(target,failed)
  os.replace(backup,target)
  atomic(root/"status.json",{"phase":"rolled-back","target":str(target),"nonce":d["nonce"]})
  start(target,d,False)
  return False
def run(plan):
 d,root,target,artifact=configuration(plan)
 wait=parent_waiter(d["parentPid"])
 atomic(root/"ready.json",{"ready":True,"nonce":d["nonce"]})
 def committed_wait():
  wait()
  if(root/"cancel.json").exists()or json.loads((root/"commit.json").read_text()).get("nonce")!=d["nonce"]:raise RuntimeError("Update not committed")
 if not swap(d,root,target,artifact,committed_wait):raise RuntimeError("Update rolled back; previous Frame reopened")
def main():
 try:
  if sys.argv[1]=="prepare":prepare(sys.argv[2])
  elif sys.argv[1]=="run":run(sys.argv[2])
  else:raise ValueError("Invalid command")
 except Exception:
  if len(sys.argv)>2:
   try:atomic(P(sys.argv[2]).parent/"error.json",{"error":"Обновление не применено. Прежняя версия сохранена."})
   except Exception:pass
  raise
if __name__=="__main__":main()
