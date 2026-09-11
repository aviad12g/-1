#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert as recover_xnf

PREFIX_V15='SAT-RAG-V15|'
TOTAL=5.0
MAX_DOWNLOAD=35_000_000
MAX_RAW=180_000_000
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']
SHARD=int(os.environ.get('SHARD','0'));NSHARDS=int(os.environ.get('NSHARDS','8'))

def selected_rows(path):
    with open(path,newline='') as f:return list(csv.DictReader(f))

def remaining_unseen(rows):
    seen={x.strip() for x in Path('v15_seen_hashes.txt').read_text().splitlines() if x.strip()}
    cand=[r for r in rows if r['hash'] not in seen]
    cand.sort(key=lambda r:hashlib.sha256((PREFIX_V15+r['hash']).encode()).hexdigest())
    excluded150={r['hash'] for r in cand[:150]}
    return [r for r in rows if r['hash'] not in seen and r['hash'] not in excluded150]

def normalize(data):
    codec='plain'
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data);codec='xz'
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data);codec='gz'
    elif data.startswith(b'BZh'):raw=bz2.decompress(data);codec='bz2'
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('too_large_after_decompress')
    return raw,codec

def download(h,p):
    try:
        with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=45) as f:data=f.read(MAX_DOWNLOAD+1)
        if len(data)>MAX_DOWNLOAD:return {'download':'too_large_download','download_bytes':len(data)}
        raw,codec=normalize(data);p.write_bytes(raw)
        return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'codec':codec,'sha256_cnf':hashlib.sha256(raw).hexdigest()}
    except Exception as e:return {'download':'failed','error':str(e)}

def header(path):
    with open(path,errors='ignore') as f:
        for line in f:
            if line.startswith('p cnf '):
                q=line.split();return int(q[2]),int(q[3])
    raise ValueError('missing p cnf header')

def sample_gate(path,maxc=4096):
    t=time.perf_counter();total=short=rep=0;seen=set();cur=[]
    with open(path,errors='ignore') as f:
      done=False
      for line in f:
        s=line.strip()
        if not s or s.startswith('c') or s.startswith('p '):continue
        if s.startswith('%'):break
        for tok in s.split():
          x=int(tok)
          if x:cur.append(x)
          else:
            total+=1
            if 1<=len(cur)<=6 and len({abs(v) for v in cur})==len(cur):
                short+=1;key=tuple(sorted(abs(v) for v in cur))
                if key in seen:rep+=1
                else:seen.add(key)
            cur=[]
            if total>=maxc:done=True;break
        if done:break
    sf=short/max(1,total);df=rep/max(1,short)
    return {'sample_s':time.perf_counter()-t,'sample_clauses':total,'short_frac':sf,'dup_frac':df,'sample_candidate':sf>=.95 and df>=.25}

def iter_cnf(path):
    cur=[]
    with open(path,errors='ignore') as f:
      for line in f:
        s=line.strip()
        if not s or s.startswith('c') or s.startswith('p '):continue
        if s.startswith('%'):break
        for tok in s.split():
          x=int(tok)
          if x:cur.append(x)
          else:yield tuple(cur);cur=[]
    if cur:yield tuple(cur)

def parse_model(text):
    m={}
    for line in text.splitlines():
        if not line.startswith('v '):continue
        for tok in line[2:].split():
            try:x=int(tok)
            except:continue
            if x:m[abs(x)]=x>0
    return m

def verify_model(path,text):
    t=time.perf_counter();m=parse_model(text);ok=bool(m) and all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path));return ok,time.perf_counter()-t

def run_proc(cmd,timeout):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=max(.001,timeout));wall=time.perf_counter()-t
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'stdout':'','rc':124}
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else ('TIMEOUT' if p.returncode in (0,124) else 'ERROR')
    return {'status':st,'wall_s':wall,'stdout':p.stdout,'rc':p.returncode}

def run_kissat(kissat,path,budget):return run_proc([kissat,'--quiet','--seed=0',str(path)],budget)

def run_cms(cms,path,budget):return run_proc([cms,*CMS_OPTS,str(path)],budget)

def checked_result(res,path):
    vtime=0;ok=''
    if res['status']=='SAT':ok,vtime=verify_model(path,res['stdout']);res['status']='SAT' if ok else 'ERROR'
    return {'status':res['status'],'algorithm_s':res['wall_s'],'verify_s':vtime,'model_ok':ok,'rc':res['rc']}

def run_portfolio(path,kissat,xorricane):
    t0=time.perf_counter();n,m=header(path);feat={'n':n,'m':m};sg=sample_gate(path);feat.update(sg)
    def remain():return TOTAL-(time.perf_counter()-t0)
    def finish_external(res,route):
        alg=time.perf_counter()-t0;cr=checked_result(res,path);return {**feat,**cr,'portfolio_algorithm_s':alg,'route':route,'routed_xnf':route.startswith('xnf-')}
    if not sg['sample_candidate'] or n>10000 or m>50000:
        return finish_external(run_kissat(kissat,path,remain()),'kissat-fast-fallback')
    xnf=Path(str(path)+'.v16.xnf');tc=time.perf_counter()
    try:meta=recover_xnf(path,xnf);conv=time.perf_counter()-tc
    except Exception as e:
        feat.update(recovery_error=str(e));return finish_external(run_kissat(kissat,path,remain()),'kissat-recovery-error')
    feat.update(recovery_s=conv,xors=meta.get('xors',0),xnf_ratio=meta.get('compression_ratio',1.0),xor_density=meta.get('xors',0)/max(1,n))
    candidate=(meta.get('xors',0)>=500 and feat['xor_density']>=.47 and feat['xnf_ratio']<=.66)
    feat['xnf_candidate']=candidate
    if not candidate:
        xnf.unlink(missing_ok=True);return finish_external(run_kissat(kissat,path,remain()),'kissat-structure-abstain')
    # 100ms escape hatch catches easy instances before specialist takeover.
    probe=run_kissat(kissat,path,min(.10,max(.001,remain())))
    feat['kissat_probe_s']=probe['wall_s'];feat['kissat_probe_status']=probe['status']
    if probe['status'] in ('SAT','UNSAT'):
        xnf.unlink(missing_ok=True);return finish_external(probe,'xnf-candidate-kissat-probe')
    xr=run_proc([xorricane,'-vb','0','-t','2','-il','-1',str(xnf)],min(2.25,max(.001,remain())))
    feat['xorricane_s']=xr['wall_s'];feat['xorricane_status']=xr['status']
    if xr['status'] in ('SAT','UNSAT'):
        xnf.unlink(missing_ok=True);return finish_external(xr,'xnf-xorricane')
    xnf.unlink(missing_ok=True)
    fb=run_kissat(kissat,path,max(.001,remain()))
    return finish_external(fb,'xnf-kissat-final-fallback')

def main():
    root=Path(f'v16_frozen_{SHARD}');root.mkdir(exist_ok=True)
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/selected_benchmarks.csv',root/'selected_benchmarks.csv')
    allrem=remaining_unseen(selected_rows(root/'selected_benchmarks.csv'))
    shard=[(i,r) for i,r in enumerate(allrem) if i%NSHARDS==SHARD]
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];xorricane=os.environ['XORRICANE']
    results=[];receipts=[]
    for gi,r in shard:
        p=root/(r['hash']+'.cnf');rec={'remaining_index':gi,'hash':r['hash'],'family':r['family'],'known':r['result'],**download(r['hash'],p)};receipts.append(rec);print('DOWNLOAD',json.dumps(rec),flush=True)
        if rec['download']!='ok':continue
        # Baseline/portfolio order deterministic per hash.
        order=['kissat','v16'];random.Random(int(r['hash'][:16],16)^0x1600F00D).shuffle(order);v16row=None
        for variant in order:
            if variant=='kissat':cr=checked_result(run_kissat(kissat,p,TOTAL),p);row={'remaining_index':gi,'hash':r['hash'],'family':r['family'],'known':r['result'],'variant':'kissat',**cr}
            else:
                cr=run_portfolio(p,kissat,xorricane);row={'remaining_index':gi,'hash':r['hash'],'family':r['family'],'known':r['result'],'variant':'v16',**cr};v16row=row
            results.append(row);print('ROW',json.dumps(row),flush=True)
        # Strong specialist control only if frozen router actually considered it a candidate.
        if v16row and v16row.get('xnf_candidate'):
            cr=checked_result(run_cms(cms,p,TOTAL),p);row={'remaining_index':gi,'hash':r['hash'],'family':r['family'],'known':r['result'],'variant':'cms_candidate_control',**cr};results.append(row);print('ROW',json.dumps(row),flush=True)
        p.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2))
    fields=sorted({k for r in results for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(results)
    bad=[]
    for r in results:
        if r.get('status')=='SAT' and str(r.get('model_ok')).lower()=='false':bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch',**r})
    for h in {r['hash'] for r in results}:
        ss={r['status'] for r in results if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2));print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
