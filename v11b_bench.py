#!/usr/bin/env python3
import argparse,csv,json,math,os,random,re,subprocess,time
from pathlib import Path
import numpy as np

def random_3sat(n,m,seed):
    r=random.Random(seed); out=[]
    for _ in range(m):
        vs=r.sample(range(1,n+1),3)
        out.append(tuple(v if r.getrandbits(1) else -v for v in vs))
    return out

def arrays(cs,n):
    vv=np.empty((len(cs),3),np.int32); ss=np.empty((len(cs),3),float)
    for i,c in enumerate(cs):
        for j,l in enumerate(c): vv[i,j]=abs(l)-1; ss[i,j]=1.0 if l>0 else -1.0
    occ=np.maximum(np.bincount(vv.ravel(),minlength=n).astype(float),1.0)
    return vv,ss,occ

def loss_grad(y,vv,ss,occ,lam=0.0):
    q=(1-ss*y[vv])*.5
    gl=np.empty_like(q)
    gl[:,0]=(-.5*ss[:,0])*q[:,1]*q[:,2]
    gl[:,1]=(-.5*ss[:,1])*q[:,0]*q[:,2]
    gl[:,2]=(-.5*ss[:,2])*q[:,0]*q[:,1]
    g=np.zeros_like(y); np.add.at(g,vv.ravel(),gl.ravel()); g/=occ
    if lam: g += (-2*lam*y)/occ
    return g

def count_unsat(a,vv,ss): return int((~((ss*a[vv])>0).any(1)).sum())

def vector_prior(cs,n,seed,restarts=2,steps=80):
    t0=time.perf_counter(); vv,ss,occ=arrays(cs,n); rng=np.random.default_rng(seed); rows=[]
    for r in range(restarts):
        y=np.zeros(n) if r==0 else rng.normal(0,.18,n)
        for t in range(steps):
            lam=.0004*(t/max(1,steps-1))**3
            g=loss_grad(y,vv,ss,occ,lam); eta=1/(1+.012*t)
            y=np.clip(y-np.clip(eta*g,-.15,.15),-1,1)
        a=np.where(y>=0,1,-1).astype(np.int8); rows.append((count_unsat(a,vv,ss),y.copy()))
    best=min(u for u,_ in rows); sel=[z for z in rows if z[0]<=best+2]
    w=np.array([math.exp(-1.15*(u-best)) for u,_ in sel]); Y=np.stack([y for _,y in sel])
    c=(w[:,None]*Y).sum(0)/w.sum()
    return np.where(c>=0,1,-1).astype(np.int8),np.abs(c),time.perf_counter()-t0,best

def write_cnf(p,cs,n):
    with open(p,'w') as f:
        f.write(f'p cnf {n} {len(cs)}\n')
        for c in cs:f.write(' '.join(map(str,c))+' 0\n')

def write_hints(p,phase,conf):
    with open(p,'w') as f:
        for i,(ph,co) in enumerate(zip(phase,conf),1): f.write(f'{i} {int(ph)} {float(co):.9f}\n')

def stat(text,key):
    m=re.search(rf'(?im)^c\s+{re.escape(key)}\s*:\s*([0-9,]+)',text)
    return int(m.group(1).replace(',','')) if m else None

def model(text,n):
    vals={}
    for line in text.splitlines():
        if line.startswith('v '):
            for t in line[2:].split():
                try:x=int(t)
                except:continue
                if x:vals[abs(x)]=1 if x>0 else -1
    return [0]+[vals.get(i,0) for i in range(1,n+1)] if len(vals)>=n else None

def verify(cs,mod):
    return mod is not None and all(any((l>0 and mod[abs(l)]>0) or (l<0 and mod[abs(l)]<0) for l in c) for c in cs)

def run(binpath,cnf,timeout,hints=None,threshold=.9):
    env=os.environ.copy()
    if hints:
        env['KISSAT_V11_HINTS']=str(hints); env['KISSAT_V11_THRESHOLD']=str(threshold)
    else:
        env.pop('KISSAT_V11_HINTS',None); env.pop('KISSAT_V11_THRESHOLD',None)
    t=time.perf_counter()
    try:
        r=subprocess.run([binpath,'--statistics',f'--time={timeout}',str(cnf)],capture_output=True,text=True,env=env,timeout=timeout+5)
        wall=time.perf_counter()-t; text=r.stdout+'\n'+r.stderr
        status='SAT' if r.returncode==10 else 'UNSAT' if r.returncode==20 else 'UNKNOWN'
        if status=='UNKNOWN' and wall<0.05:
            print('FAST_UNKNOWN',r.returncode,text[-1000:],flush=True)
        n=int(next(line.split()[2] for line in open(cnf) if line.startswith('p ')))
        return dict(status=status,wall_s=wall,decisions=stat(text,'decisions'),conflicts=stat(text,'conflicts'),propagations=stat(text,'propagations'),restarts=stat(text,'restarts'),model=model(text,n))
    except subprocess.TimeoutExpired:
        return dict(status='TIMEOUT',wall_s=time.perf_counter()-t,decisions=None,conflicts=None,propagations=None,restarts=None,model=None)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('kissat'); ap.add_argument('--sizes',default='200,300,400'); ap.add_argument('--seeds',type=int,default=4); ap.add_argument('--timeout',type=int,default=8); ap.add_argument('--thresholds',default='.80,.90,.95'); ap.add_argument('--out',default='v11b_results.csv')
    a=ap.parse_args(); sizes=[int(x) for x in a.sizes.split(',')]; ths=[float(x) for x in a.thresholds.split(',')]
    root=Path('v11b_tmp');root.mkdir(exist_ok=True); rows=[]; errors=[]
    for n in sizes:
      for j in range(a.seeds):
        seed=11000+n*101+j*7919; cs=random_3sat(n,round(4.26*n),seed); cnf=root/f'n{n}_{seed}.cnf';write_cnf(cnf,cs,n)
        phase,conf,prep,best=vector_prior(cs,n,seed^0x8172)
        rr=random.Random(seed^0xC0FFEE); rphase=np.array([1 if rr.getrandbits(1) else -1 for _ in range(n)],np.int8)
        hp=root/f'n{n}_{seed}_vector.hints';write_hints(hp,phase,conf)
        rp=root/f'n{n}_{seed}_random.hints';write_hints(rp,rphase,conf)
        variants=[('baseline',None,None,0.0)]
        for th in ths: variants += [(f'random_t{th:.2f}',rp,th,0.0),(f'vector_t{th:.2f}',hp,th,prep)]
        solved={}
        for name,hints,th,pre in variants:
            res=run(a.kissat,cnf,a.timeout,hints,th if th is not None else .9); mod=res.pop('model'); valid=''
            if res['status']=='SAT': valid=verify(cs,mod); errors += [] if valid else [(n,seed,name,'invalid-model')]
            row={'n':n,'m':len(cs),'seed':seed,'variant':name,'threshold':th if th is not None else '', 'hint_fraction':float((conf>=th).mean()) if th is not None else 0.0,'vector_prep_s':pre,'vector_best_unsat':best,'model_valid':valid,**res}
            row['total_s']=row['wall_s']+pre;rows.append(row);solved[name]=row['status'];print('ROW',json.dumps(row),flush=True)
        vals={v for v in solved.values() if v not in ('TIMEOUT','UNKNOWN')}
        if len(vals)>1: errors.append((n,seed,'status-mismatch',solved))
    with open(a.out,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    Path('v11b_summary.json').write_text(json.dumps({'rows':len(rows),'errors':errors},indent=2));print('ERRORS',errors)
    if errors: raise SystemExit(2)
if __name__=='__main__':main()
