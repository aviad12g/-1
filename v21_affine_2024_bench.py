#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path

TIMEOUT=15.0
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'): return lzma.decompress(data)
    if data.startswith(b'\x1f\x8b'): return gzip.decompress(data)
    if data.startswith(b'BZh'): return bz2.decompress(data)
    return data

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:d=f.read(35_000_001)
    if len(d)>35_000_000: raise ValueError('too_large_download')
    raw=normalize(d)
    if len(raw)>160_000_000: raise ValueError('too_large_after_decompress')
    p.write_bytes(raw)
    return len(d),len(raw),hashlib.sha256(raw).hexdigest()

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

def verify(path,m):
    return all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def run(cmd,path,timeout=TIMEOUT):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=timeout+0.5)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else ('TIMEOUT' if p.returncode in (0,124) else 'ERROR')
    ok=verify(path,parse_model(p.stdout)) if st=='SAT' else ''
    return {'status':st,'wall_s':wall,'model_ok':ok,'returncode':p.returncode,'stdout_tail':p.stdout[-1000:]}

def parse_router(text,rc,wall):
    js=None
    for line in reversed(text.splitlines()):
        if line.startswith('{') and line.endswith('}'):
            try:js=json.loads(line);break
            except:pass
    if js is None:return {'status':'ERROR','wall_s':wall,'route':'','model_ok':'','returncode':rc,'stdout_tail':text[-1000:]}
    return {'status':js.get('status','ERROR'),'wall_s':wall,'route':js.get('route',''),'model_ok':js.get('model_ok',''),'returncode':rc,'equations':js.get('equations'),'sample_s':js.get('sample_s'),'router_total_s':js.get('total_s'),'stdout_tail':text[-1000:]}

def run_router(router,kissat,cms,path):
    cmd=[router,str(path),'--kissat',kissat,'--cms',cms,'--budget-ms','15000','--pre-ms','1500','--mixed-ms','5000']
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=15.75)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'route':'','model_ok':''}
    return parse_router(p.stdout,p.returncode,time.perf_counter()-t)

def main():
    root=Path('v21_affine_2024');root.mkdir(exist_ok=True)
    cand=list(csv.DictReader(open('v21_affine_2024_candidates.csv')))
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];router=os.environ['ROUTER']
    out=[];receipts=[]
    for r in cand:
        h=r['hash'];cnf=root/(h+'.cnf');rec=dict(r)
        try:
            db,rb,sha=download(h,cnf);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,actual_sha256=sha)
            if sha!=r['sha256_cnf']:raise ValueError('sha256_mismatch')
        except Exception as e:
            rec.update(download='failed',error=str(e));receipts.append(rec);continue
        receipts.append(rec)
        variants=['kissat','cms','v21_router']
        random.Random(int(h[:16],16)^0x21002100).shuffle(variants)
        for v in variants:
            if v=='kissat':res=run([kissat,'--quiet','--seed=0',str(cnf)],cnf)
            elif v=='cms':res=run([cms,*CMS_OPTS,str(cnf)],cnf)
            else:res=run_router(router,kissat,cms,cnf)
            row={**r,'variant':v,**res};out.append(row);print('ROW',json.dumps(row),flush=True)
        cnf.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2))
    fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and str(r.get('model_ok')).lower() not in ('true','1'):bad.append({'type':'invalid_model',**r})
    for h in {r['hash'] for r in out}:
        ss={r['status'] for r in out if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    direct=sum(1 for r in out if r['variant']=='v21_router' and r.get('route')=='direct-affine')
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'direct_affine_routes':direct,'bad':bad},indent=2))
    print('VALIDATION',json.dumps({'n_bad':len(bad),'direct_affine_routes':direct}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
