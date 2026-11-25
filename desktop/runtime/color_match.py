"""Bounded reference look, fitted in decorrelated luma/chroma coordinates; native .cube."""
import subprocess,json,hashlib,math
from pathlib import Path
import numpy as np
# Orthonormal opponent RGB coordinates; not a claim of calibrated perceptual DeltaE.
M=np.array([[1,1,1],[1,0,-1],[1,-2,1]],dtype=float);M/=np.linalg.norm(M,axis=1)[:,None]
def pixels(path):
 r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(path),'-vf','scale=320:180','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=45)
 if r.returncode or len(r.stdout)!=320*180*3:raise ValueError('Не удалось прочитать кадр цвета')
 x=np.frombuffer(r.stdout,dtype=np.uint8).reshape(-1,3)/255;keep=(x.mean(axis=1)>.025)&(x.mean(axis=1)<.97)
 if keep.sum()<300:raise ValueError('Кадр слишком тёмный/пустой для подбора')
 return x[keep]
def fit(source,reference,dest,strength=.55,protect_skin=True):
 strength=float(strength)
 if not 0<=strength<=1:raise ValueError('Сила look:0..1')
 a=pixels(source);b=pixels(reference);ac=a@M.T;bc=b@M.T;ma=np.median(ac,axis=0);mb=np.median(bc,axis=0)
 std_a=np.percentile(ac,80,axis=0)-np.percentile(ac,20,axis=0);std_b=np.percentile(bc,80,axis=0)-np.percentile(bc,20,axis=0);gain=np.clip((std_b+.02)/(std_a+.02),.8,1.2);shift=np.clip(mb-ma,[-.16,-.09,-.09],[.16,.09,.09])
 # A monotone five-point luma curve; endpoints and correction amplitude are bounded.
 q=np.array([0,.1,.3,.5,.7,.9,1]);xq=np.quantile(ac[:,0],q);yq=np.quantile(bc[:,0],q);yq=xq+np.clip(yq-xq,-.16,.16);yq=np.maximum.accumulate(yq)
 def transform(rgb):
  c=rgb@M.T;out=(c-ma)*gain+ma+shift;out[:,0]=np.interp(c[:,0],xq,yq);mapped=out@M;delta=np.clip(mapped-rgb,-.16,.16);weight=np.full((len(rgb),1),strength)
  if protect_skin:
   # Broad warm-color guard, not face or ethnicity detection.
   warm=(rgb[:,0]>rgb[:,1])&(rgb[:,1]>rgb[:,2])&((rgb.max(axis=1)-rgb.min(axis=1))>.06)&(rgb.mean(axis=1)>.15)
   weight[warm]*=.65
  return np.clip(rgb+delta*weight,0,1)
 side=17;rows=[]
 for bl in np.linspace(0,1,side):
  for gr in np.linspace(0,1,side):
   for red in np.linspace(0,1,side):rows.append([red,gr,bl])
 lut=transform(np.array(rows));text='TITLE "Frame bounded reference look"\nLUT_3D_SIZE 17\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n'+'\n'.join(' '.join(f'{v:.7f}'for v in row)for row in lut)+'\n';Path(dest).write_text(text)
 before=float(np.linalg.norm(np.median(a,axis=0)-np.median(b,axis=0)));after=float(np.linalg.norm(np.median(transform(a),axis=0)-np.median(b,axis=0)))
 return {'strength':strength,'protectWarmColors':bool(protect_skin),'grid':side,'sha256':hashlib.sha256(Path(dest).read_bytes()).hexdigest(),'medianRGBDistanceBefore':round(before,5),'medianRGBDistanceAfter':round(after,5),'method':'bounded opponent-color transfer + monotone luma quantiles; native17cube; review required, not guaranteed style match'}
def preview(source,lut,dest):
 left=Path(dest).with_suffix('.left.png');right=Path(dest).with_suffix('.right.png')
 r=subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(source),'-filter_complex_threads','1','-filter_complex',f'[0:v]split[a][b];[b]lut3d=file={lut}[c];[a][c]hstack=inputs=2,scale=1280:-2[v]','-map','[v]','-frames:v','1','-y',str(dest)],capture_output=True,timeout=60)
 if r.returncode:raise ValueError('Не удалось собрать сравнение look')
 return dest
