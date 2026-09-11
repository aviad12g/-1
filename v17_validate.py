#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,math,os,random,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert

TIMEOUT=15.0
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

def run(cmd,path,timeout):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=max(.01,timeout))
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','solver_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else ('TIMEOUT' if p.returncode in (0,124) else 'ERROR')
    vt=0.0;ok=''
    if st=='SAT':
        q=time.perf_counter();ok=verify(path,parse_model(p.stdout));vt=time.perf_counter()-q
    return {'status':st,'solver_s':wall,'verify_s':vt,'model_ok':ok,'returncode':p.returncode}

def main():
    root=Path('v17_validate');root.mkdir(exist_ok=True)
    allrows=list(csv.DictReader(open('v17_routed_candidates.csv')))
    selected=[r for r in allrows if r['prior_control'].strip().lower()=='false']
    Path(root/'frozen_candidates.csv').write_text(Path('v17_routed_candidates.csv').read_text())
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];xorricane=os.environ['XORRICANE']
    out=[];receipts=[]
    for r in selected:
        h=r['hash'];cnf=root/(h+'.cnf');xnf=root/(h+'.xnf');rec={'global_rank':r['global_rank'],'hash':h,'family':r['family'],'known':r['known'],'largest_xor_comp_vars':r['largest_xor_comp_vars'],'gate_condensation_depth':r['gate_condensation_depth']}
        try:
            db,rb,sha=download(h,cnf);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,sha256_cnf=sha)
        except Exception as e:rec.update(download='failed',error=str(e));receipts.append(rec);continue
        receipts.append(rec);print('DOWNLOAD',json.dumps(rec),flush=True)
        variants=['kissat','cms'];random.Random(int(h[:16],16)^0x171717).shuffle(variants)
        for v in variants:
            if v=='kissat':res=run([kissat,'--quiet','--seed=0',str(cnf)],cnf,TIMEOUT)
            else:res=run([cms,*CMS_OPTS,str(cnf)],cnf,TIMEOUT)
            row={**rec,'variant':v,'convert_s':0.0,'total_algorithm_s':res['solver_s'],**res};out.append(row);print('ROW',json.dumps(row),flush=True)
        # Exact recovery and XNF solving share the same fixed total algorithm budget.
        t=time.perf_counter();meta={};conv_error=''
        try:meta=convert(cnf,xnf)
        except Exception as e:conv_error=str(e)
        conv=time.perf_counter()-t;remaining=TIMEOUT-conv
        if conv_error:
            res={'status':'ERROR','solver_s':0.0,'verify_s':0.0,'model_ok':'','returncode':-1}
        elif remaining<=0:
            res={'status':'TIMEOUT','solver_s':0.0,'verify_s':0.0,'model_ok':'','returncode':124}
        else:
            inner=max(1,int(math.ceil(remaining)))
            res=run([xorricane,'-vb','0','-t',str(inner),'-il','-1','-delh','lbd',str(xnf)],cnf,remaining)
        total=min(TIMEOUT,conv+res['solver_s']) if res['status']=='TIMEOUT' else conv+res['solver_s']
        row={**rec,'variant':'v17_xnf','convert_s':conv,'total_algorithm_s':total,'xors':meta.get('xors'),'compression_ratio':meta.get('compression_ratio'),'conversion_error':conv_error,**res};out.append(row);print('ROW',json.dumps(row),flush=True)
        cnf.unlink(missing_ok=True);xnf.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2));fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and r.get('model_ok') is False:bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch',**r})
    for h in {r['hash'] for r in out}:
        ss={r['status'] for r in out if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2));print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
