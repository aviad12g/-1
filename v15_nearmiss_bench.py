#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path

TIMEOUT=10.0
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'): raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'): raw=gzip.decompress(data)
    elif data.startswith(b'BZh'): raw=bz2.decompress(data)
    else: raw=data
    if len(raw)>160_000_000: raise ValueError('too_large_after_decompress')
    return raw

def download(h,path):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(35_000_001)
    if len(data)>35_000_000: raise ValueError('too_large_download')
    raw=normalize(data);path.write_bytes(raw)
    return len(data),len(raw),hashlib.sha256(raw).hexdigest()

def iter_cnf(path):
    cur=[]
    with open(path,errors='ignore') as f:
      for line in f:
        s=line.strip()
        if not s or s.startswith('c') or s.startswith('p '): continue
        if s.startswith('%'): break
        for tok in s.split():
          x=int(tok)
          if x: cur.append(x)
          else: yield tuple(cur);cur=[]
    if cur: yield tuple(cur)

def parse_model(text):
    m={}
    for line in text.splitlines():
        if not line.startswith('v '): continue
        for tok in line[2:].split():
            try:x=int(tok)
            except:continue
            if x:m[abs(x)]=x>0
    return m

def verify(path,m): return all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def run_external(cmd,path):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t; st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'ERROR'
    ok=verify(path,parse_model(p.stdout)) if st=='SAT' else ''
    return {'status':st,'wall_s':wall,'model_ok':ok}

def run_router(binpath,path,kissat,cms):
    t=time.perf_counter()
    try:p=subprocess.run([binpath,str(path),'--kissat',kissat,'--cms',cms,'--budget-ms','10000','--pre-ms','250','--mixed-ms','8000'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+1)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'route':'outer-timeout','model_ok':''}
    wall=time.perf_counter()-t
    try:d=json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:return {'status':'ERROR','wall_s':wall,'route':'json-error','model_ok':'','raw':p.stdout[-500:]}
    keep=['status','route','model_ok','total_s','analysis_s','solver_s','verify_s','sample_s','equations','internal_frac','output_ratio','projected_xors','other_clauses']
    out={k:d.get(k) for k in keep};out['wall_s']=wall;return out

def main():
    root=Path('v15_nearmiss');root.mkdir(exist_ok=True)
    rows=list(csv.DictReader(open('v15_nearmiss_candidates.csv')))
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];frozen=os.environ['V15'];force=os.environ['V15_FORCE']
    out=[];receipts=[]
    for r in rows:
        path=root/(r['hash']+'.cnf')
        rec={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'struct_score':r['struct_score']}
        try:
            db,rb,sha=download(r['hash'],path);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,sha256_cnf=sha)
        except Exception as e:
            rec.update(download='failed',error=str(e));receipts.append(rec);continue
        receipts.append(rec)
        variants=['kissat','cms','v15_frozen','v15_force'];random.Random(int(r['hash'][:16],16)^0xD3ADB33F).shuffle(variants)
        for v in variants:
            if v=='kissat':res=run_external([kissat,'--quiet','--seed=0',str(path)],path)
            elif v=='cms':res=run_external([cms,*CMS_OPTS,str(path)],path)
            elif v=='v15_frozen':res=run_router(frozen,path,kissat,cms)
            else:res=run_router(force,path,kissat,cms)
            row={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'struct_score':r['struct_score'],'variant':v,**res};out.append(row);print('ROW',json.dumps(row),flush=True)
        path.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2))
    fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and str(r.get('model_ok')).lower()=='false':bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch',**r})
    for h in {r['hash'] for r in out}:
        ss={r['status'] for r in out if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2))
    print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)

if __name__=='__main__':main()
