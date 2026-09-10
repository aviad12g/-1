#!/usr/bin/env python3
import argparse,csv,json,os,random,re,subprocess,time
from pathlib import Path

def random_3sat(n,m,seed):
    r=random.Random(seed); out=[]
    for _ in range(m):
        vs=r.sample(range(1,n+1),3)
        out.append(tuple(v if r.getrandbits(1) else -v for v in vs))
    return out

def write_cnf(p,cs,n):
    with open(p,'w') as f:
        f.write(f'p cnf {n} {len(cs)}\n')
        for c in cs:f.write(' '.join(map(str,c))+' 0\n')

def model(text,n):
    vals={}
    for line in text.splitlines():
        if line.startswith('v '):
            for t in line[2:].split():
                try:x=int(t)
                except:continue
                if x: vals[abs(x)]=1 if x>0 else -1
    return [0]+[vals.get(i,0) for i in range(1,n+1)] if len(vals)>=n else None

def verify(cs,mod):
    return mod is not None and all(any((l>0 and mod[abs(l)]>0) or (l<0 and mod[abs(l)]<0) for l in c) for c in cs)

def stat(text,key):
    m=re.search(rf'(?im)^c\s+{re.escape(key)}\s*:\s*([0-9,]+)',text)
    return int(m.group(1).replace(',','')) if m else None

def run(binpath,cnf,timeout,mode,conf,cap,max_size,max_glue):
    env=os.environ.copy(); env['KISSAT_V12_MODE']=mode
    env['KISSAT_V12_CONF']=str(conf); env['KISSAT_V12_CAP']=str(cap)
    env['KISSAT_V12_MAX_SIZE']=str(max_size); env['KISSAT_V12_MAX_GLUE']=str(max_glue)
    t=time.perf_counter()
    try:
        r=subprocess.run([binpath,'--statistics',f'--time={timeout}',str(cnf)],capture_output=True,text=True,env=env,timeout=timeout+5)
        wall=time.perf_counter()-t; text=r.stdout+'\n'+r.stderr
        status='SAT' if r.returncode==10 else 'UNSAT' if r.returncode==20 else 'UNKNOWN'
        n=int(next(line.split()[2] for line in open(cnf) if line.startswith('p ')))
        return dict(status=status,wall_s=wall,model=model(text,n),decisions=stat(text,'decisions'),conflicts=stat(text,'conflicts'),
                    v12_seen_conflicts=stat(text,'v12_seen_conflicts'),v12_stored_clauses=stat(text,'v12_stored_clauses'),
                    v12_retrievals=stat(text,'v12_retrievals'),v12_hint_uses=stat(text,'v12_hint_uses'),v12_random_uses=stat(text,'v12_random_uses'))
    except subprocess.TimeoutExpired as e:
        text=((e.stdout or '') if isinstance(e.stdout,str) else '')+'\n'+((e.stderr or '') if isinstance(e.stderr,str) else '')
        return dict(status='TIMEOUT',wall_s=time.perf_counter()-t,model=None,decisions=stat(text,'decisions'),conflicts=stat(text,'conflicts'),
                    v12_seen_conflicts=stat(text,'v12_seen_conflicts'),v12_stored_clauses=stat(text,'v12_stored_clauses'),
                    v12_retrievals=stat(text,'v12_retrievals'),v12_hint_uses=stat(text,'v12_hint_uses'),v12_random_uses=stat(text,'v12_random_uses'))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('kissat'); ap.add_argument('--sizes',default='200,300,400'); ap.add_argument('--seeds',type=int,default=4)
    ap.add_argument('--seed-offset',type=int,default=0); ap.add_argument('--timeout',type=int,default=8); ap.add_argument('--confs',default='.65,.75'); ap.add_argument('--cap',type=int,default=256)
    ap.add_argument('--max-size',type=int,default=12); ap.add_argument('--max-glue',type=int,default=6); ap.add_argument('--out',default='v12_results.csv')
    a=ap.parse_args(); sizes=[int(x) for x in a.sizes.split(',')]; confs=[float(x) for x in a.confs.split(',')]
    root=Path('v12_tmp'); root.mkdir(exist_ok=True); rows=[]; errors=[]
    for n in sizes:
      for j in range(a.seeds):
        seed=a.seed_offset+11000+n*101+j*7919; cs=random_3sat(n,round(4.26*n),seed); cnf=root/f'n{n}_{seed}.cnf'; write_cnf(cnf,cs,n)
        variants=[('off','off',0.0)]
        for c in confs: variants += [(f'random_c{c:.2f}','random',c),(f'conflict_c{c:.2f}','conflict',c)]
        statuses={}
        for name,mode,c in variants:
            res=run(a.kissat,cnf,a.timeout,mode,c,a.cap,a.max_size,a.max_glue); mod=res.pop('model'); valid=''
            if res['status']=='SAT': valid=verify(cs,mod); errors += [] if valid else [(n,seed,name,'invalid-model')]
            row={'n':n,'m':len(cs),'seed':seed,'seed_offset':a.seed_offset,'variant':name,'mode':mode,'conf_threshold':c,'model_valid':valid,**res}
            rows.append(row); statuses[name]=row['status']; print('ROW',json.dumps(row),flush=True)
        vals={v for v in statuses.values() if v not in ('TIMEOUT','UNKNOWN')}
        if len(vals)>1: errors.append((n,seed,'status-mismatch',statuses))
    with open(a.out,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    Path(a.out).with_suffix('.json').write_text(json.dumps({'rows':len(rows),'errors':errors,'seed_offset':a.seed_offset},indent=2))
    print('ERRORS',errors)
    if errors: raise SystemExit(2)
if __name__=='__main__': main()
