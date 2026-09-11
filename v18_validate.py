#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,math,os,random,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert

TIMEOUT=15.0
PROOF_TIMEOUT=90.0
MAX_DOWNLOAD=25_000_000
MAX_RAW=120_000_000
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('decompressed_too_large')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:raise ValueError('download_too_large')
    raw=normalize(data);p.write_bytes(raw);return len(data),len(raw),hashlib.sha256(raw).hexdigest()

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

def verify(path,m):return bool(m) and all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def classify(rc,out):
    if rc==10 or 's SATISFIABLE' in out:return 'SAT'
    if rc==20 or 's UNSATISFIABLE' in out:return 'UNSAT'
    return 'ERROR'

def run(cmd,cnf,timeout):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=max(.01,timeout))
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','solver_s':time.perf_counter()-t,'model_ok':'','returncode':124,'stdout_tail':''}
    wall=time.perf_counter()-t;st=classify(p.returncode,p.stdout);ok='';vt=0.0
    if st=='SAT':
        q=time.perf_counter();ok=verify(cnf,parse_model(p.stdout));vt=time.perf_counter()-q
    return {'status':st,'solver_s':wall,'verify_s':vt,'model_ok':ok,'returncode':p.returncode,'stdout_tail':p.stdout[-2000:]}

def main():
    root=Path('v18_validate');root.mkdir(exist_ok=True)
    rows=list(csv.DictReader(open('v18_frozen_candidates.csv')))
    Path(root/'frozen_candidates.csv').write_text(Path('v18_frozen_candidates.csv').read_text())
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];xorricane=os.environ['XORRICANE'];xorcle=os.environ['XORCLE'];xorcle_checker=os.environ['XORCLE_CHECKER']
    out=[];receipts=[];proofs=[]
    for r in rows:
        h=r['hash'];cnf=root/(h+'.cnf');xnf=root/(h+'.xnf');rec={k:r[k] for k in r}
        db,rb,sha=download(h,cnf);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,sha256_cnf=sha);receipts.append(rec)
        # Exact conversion is shared by the two XNF paths and charged separately to each.
        t=time.perf_counter();meta=convert(cnf,xnf);conv=time.perf_counter()-t
        variants=['kissat','cms','xorricane','xorcle'];random.Random(int(h[:16],16)^0x181818).shuffle(variants)
        for v in variants:
            if v=='kissat':res=run([kissat,'--quiet','--seed=0',str(cnf)],cnf,TIMEOUT);total=res['solver_s'];charged=0.0
            elif v=='cms':res=run([cms,*CMS_OPTS,str(cnf)],cnf,TIMEOUT);total=res['solver_s'];charged=0.0
            else:
                remaining=max(0.0,TIMEOUT-conv);charged=conv
                if remaining<=0:res={'status':'TIMEOUT','solver_s':0.0,'verify_s':0.0,'model_ok':'','returncode':124,'stdout_tail':''}
                elif v=='xorricane':res=run([xorricane,'-vb','0','-t',str(max(1,int(math.ceil(remaining)))),'-il','-1','-delh','lbd',str(xnf)],cnf,remaining)
                else:res=run([xorcle,str(xnf)],cnf,remaining)
                total=min(TIMEOUT,conv+res['solver_s']) if res['status']=='TIMEOUT' else conv+res['solver_s']
            row={**rec,'variant':v,'convert_s':charged,'total_algorithm_s':total,'xors':meta.get('xors'),'compression_ratio':meta.get('compression_ratio'),**res};out.append(row);print('ROW',json.dumps({k:v for k,v in row.items() if k!='stdout_tail'}),flush=True)
        # Secondary certification run: only if primary Xorcle says UNSAT.
        xp=[z for z in out if z['hash']==h and z['variant']=='xorcle'][-1]
        if xp['status']=='UNSAT':
            proof=root/(h+'.lrup');t=time.perf_counter()
            try:
                p=subprocess.run([xorcle,'--compact=false',f'--proof={proof}',str(xnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=PROOF_TIMEOUT)
                ps=time.perf_counter()-t;proof_status=classify(p.returncode,p.stdout)
            except subprocess.TimeoutExpired:
                ps=time.perf_counter()-t;proof_status='TIMEOUT'
            verified=False;check_s=0.0;check_tail=''
            if proof_status=='UNSAT' and proof.exists():
                q=time.perf_counter();c=subprocess.run(['python3',xorcle_checker,str(xnf),str(proof)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=PROOF_TIMEOUT);check_s=time.perf_counter()-q;check_tail=c.stdout[-2000:];verified=(c.returncode==0)
            proofs.append({'hash':h,'proof_status':proof_status,'proof_s':ps,'proof_exists':proof.exists(),'proof_bytes':proof.stat().st_size if proof.exists() else 0,'check_s':check_s,'verified':verified,'check_tail':check_tail});print('PROOF',json.dumps(proofs[-1]),flush=True)
        cnf.unlink(missing_ok=True);xnf.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2));Path(root/'proofs.json').write_text(json.dumps(proofs,indent=2))
    fields=sorted({k for r in out for k in r});
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r['status']=='SAT' and r['model_ok'] is False:bad.append({'type':'invalid_model','hash':r['hash'],'variant':r['variant']})
        if r['known'] in ('sat','unsat') and r['status'] in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch','hash':r['hash'],'variant':r['variant'],'status':r['status']})
    ss={r['status'] for r in out if r['status'] in ('SAT','UNSAT')}
    if len(ss)>1:bad.append({'type':'solver_disagreement','statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2));print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
