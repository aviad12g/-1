#!/usr/bin/env python3
import argparse, csv, json, math, os, random, re, subprocess, sys, tempfile, time
from pathlib import Path
import numpy as np


def random_3sat(n, m, seed):
    rng = random.Random(seed)
    clauses=[]
    for _ in range(m):
        vs=rng.sample(range(1,n+1),3)
        clauses.append(tuple(v if rng.getrandbits(1) else -v for v in vs))
    return clauses


def arrays(clauses,n):
    m=len(clauses)
    vv=np.empty((m,3),dtype=np.int32)
    ss=np.empty((m,3),dtype=np.float64)
    for i,c in enumerate(clauses):
        for j,l in enumerate(c):
            vv[i,j]=abs(l)-1
            ss[i,j]=1.0 if l>0 else -1.0
    occ=np.bincount(vv.ravel(),minlength=n).astype(np.float64)
    return vv,ss,np.maximum(occ,1.0)


def loss_grad(y,vv,ss,occ,bin_lambda=0.0):
    q=(1.0-ss*y[vv])*0.5
    prod=q[:,0]*q[:,1]*q[:,2]
    loss=float(prod.sum())
    gl=np.empty_like(q)
    gl[:,0]=(-0.5*ss[:,0])*q[:,1]*q[:,2]
    gl[:,1]=(-0.5*ss[:,1])*q[:,0]*q[:,2]
    gl[:,2]=(-0.5*ss[:,2])*q[:,0]*q[:,1]
    g=np.zeros_like(y)
    np.add.at(g,vv.ravel(),gl.ravel())
    g/=occ
    if bin_lambda:
        loss += float(bin_lambda*np.sum(1-y*y))
        g += (-2.0*bin_lambda*y)/occ
    return loss,g


def count_unsat(a,vv,ss):
    return int((~((ss*a[vv])>0).any(axis=1)).sum())


def vector_prior(clauses,n,seed,restarts=2,steps=80,lr=1.0):
    t0=time.perf_counter(); vv,ss,occ=arrays(clauses,n)
    rng=np.random.default_rng(seed); rows=[]
    for r in range(restarts):
        y=np.zeros(n,dtype=float) if r==0 else rng.normal(0,0.18,size=n)
        for t in range(steps):
            lam=0.0004*(t/max(1,steps-1))**3
            _,g=loss_grad(y,vv,ss,occ,lam)
            eta=lr/(1+0.012*t)
            y=np.clip(y-np.clip(eta*g,-0.15,0.15),-1.0,1.0)
        a=np.where(y>=0,1,-1).astype(np.int8)
        uns=count_unsat(a,vv,ss)
        rows.append((uns,y.copy()))
    best=min(x[0] for x in rows)
    sel=[x for x in rows if x[0]<=best+2]
    weights=np.array([math.exp(-1.15*(x[0]-best)) for x in sel])
    Y=np.stack([x[1] for x in sel])
    consensus=(weights[:,None]*Y).sum(axis=0)/weights.sum()
    prior=np.where(consensus>=0,1,-1).astype(np.int8)
    return prior, float(time.perf_counter()-t0), best, float(np.mean(np.abs(consensus)))


def transform(clauses,flip):
    out=[]
    for c in clauses:
        out.append(tuple(l if flip[abs(l)-1]>0 else -l for l in c))
    return out


def write_cnf(path,clauses,n):
    with open(path,'w') as f:
        f.write(f'p cnf {n} {len(clauses)}\n')
        for c in clauses: f.write(' '.join(map(str,c))+' 0\n')


def verify(clauses,model,n):
    if model is None: return False
    for c in clauses:
        ok=False
        for l in c:
            v=model[abs(l)]
            if (l>0 and v>0) or (l<0 and v<0): ok=True; break
        if not ok: return False
    return True


def parse_stat(text,name):
    pats={
      'decisions':[r'(?im)^c\s+decisions\s*:\s*([0-9,]+)',r'(?im)^c.*?([0-9,]+)\s+decisions\b'],
      'conflicts':[r'(?im)^c\s+conflicts\s*:\s*([0-9,]+)',r'(?im)^c.*?([0-9,]+)\s+conflicts\b'],
      'propagations':[r'(?im)^c\s+propagations\s*:\s*([0-9,]+)',r'(?im)^c.*?([0-9,]+)\s+propagations\b'],
    }
    for p in pats[name]:
        m=re.search(p,text)
        if m:
            try: return int(m.group(1).replace(',',''))
            except: pass
    return None


def parse_model(text,n):
    vals={}
    for line in text.splitlines():
        if not line.startswith('v '): continue
        for tok in line[2:].split():
            try: x=int(tok)
            except: continue
            if x==0: continue
            vals[abs(x)] = 1 if x>0 else -1
    if len(vals)<n: return None
    return [0]+[vals.get(i,0) for i in range(1,n+1)]


def run_kissat(binpath,cnf,timeout_s):
    t0=time.perf_counter()
    try:
        r=subprocess.run([binpath,f'--time={timeout_s}',str(cnf)],capture_output=True,text=True,timeout=timeout_s+5)
        wall=time.perf_counter()-t0
        text=r.stdout+'\n'+r.stderr
        status='SAT' if r.returncode==10 else 'UNSAT' if r.returncode==20 else 'UNKNOWN'
        return dict(status=status,returncode=r.returncode,wall_s=wall,
                    decisions=parse_stat(text,'decisions'),conflicts=parse_stat(text,'conflicts'),
                    propagations=parse_stat(text,'propagations'),model=parse_model(text,read_nvars(cnf)),raw=text[-12000:])
    except subprocess.TimeoutExpired:
        return dict(status='TIMEOUT',returncode=124,wall_s=time.perf_counter()-t0,
                    decisions=None,conflicts=None,propagations=None,model=None,raw='TIMEOUT')


def read_nvars(cnf):
    with open(cnf) as f:
        for line in f:
            if line.startswith('p '): return int(line.split()[2])
    raise ValueError('no header')


def mapped_model(zmodel,flip):
    if zmodel is None: return None
    return [0]+[int(zmodel[i]*flip[i-1]) for i in range(1,len(zmodel))]


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('kissat'); ap.add_argument('--timeout',type=int,default=8)
    ap.add_argument('--sizes',default='200,300,400'); ap.add_argument('--seeds',type=int,default=4)
    ap.add_argument('--out',default='v11_results.csv')
    a=ap.parse_args()
    sizes=[int(x) for x in a.sizes.split(',') if x]
    root=Path('v11_tmp'); root.mkdir(exist_ok=True)
    rows=[]; mismatches=[]; invalid=[]
    meta={'kissat_version':subprocess.check_output([a.kissat,'--version'],text=True).strip(),
          'kissat_id':subprocess.check_output([a.kissat,'--id'],text=True).strip(),
          'sizes':sizes,'seeds_per_size':a.seeds,'timeout_s':a.timeout,
          'vector_restarts':2,'vector_steps':80,'ratio':4.26}
    print('META',json.dumps(meta),flush=True)
    for n in sizes:
      for j in range(a.seeds):
        seed=11000+n*101+j*7919
        clauses=random_3sat(n,round(4.26*n),seed)
        prior,prep,best_uns,conf=vector_prior(clauses,n,seed^0x8172)
        rr=random.Random(seed^0xC0FFEE); rnd=np.array([1 if rr.getrandbits(1) else -1 for _ in range(n)],dtype=np.int8)
        variants=[('baseline',np.ones(n,dtype=np.int8),0.0,best_uns,conf),
                  ('random_phase',rnd,0.0,best_uns,conf),
                  ('vector_phase',prior,prep,best_uns,conf)]
        resultset={}
        for name,flip,preps,best,cons in variants:
            f2=clauses if name=='baseline' else transform(clauses,flip)
            p=root/f'n{n}_s{seed}_{name}.cnf'; write_cnf(p,f2,n)
            res=run_kissat(a.kissat,p,a.timeout)
            model=res.pop('model'); raw=res.pop('raw')
            valid=''
            if res['status']=='SAT':
                om=model if name=='baseline' else mapped_model(model,flip)
                valid=verify(clauses,om,n)
                if not valid: invalid.append((n,seed,name))
            row={'n':n,'m':len(clauses),'seed':seed,'variant':name,'vector_prep_s':preps,
                 'vector_best_unsat':best,'vector_consensus_abs':cons,'model_valid':valid,**res}
            row['total_s']=res['wall_s']+preps
            rows.append(row); resultset[name]=res['status']
            print('ROW',json.dumps(row),flush=True)
            if res['status']=='UNKNOWN':
                (root/f'unknown_n{n}_s{seed}_{name}.log').write_text(raw)
        ss={x for x in resultset.values() if x not in ('TIMEOUT','UNKNOWN')}
        if len(ss)>1: mismatches.append((n,seed,resultset))
    fields=list(rows[0].keys()) if rows else []
    with open(a.out,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    summary={'meta':meta,'rows':len(rows),'mismatches':mismatches,'invalid_models':invalid}
    Path('v11_summary.json').write_text(json.dumps(summary,indent=2))
    print('SUMMARY',json.dumps(summary),flush=True)
    if mismatches or invalid: sys.exit(2)

if __name__=='__main__': main()
