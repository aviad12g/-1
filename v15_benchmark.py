#!/usr/bin/env python3
import bz2, csv, gzip, hashlib, json, lzma, os, random, subprocess, sys, time, urllib.request
from pathlib import Path

N_SELECT=30
TIMEOUT=5.0
PRE_MS=250
MIXED_MS=3000
PREFIX='SAT-RAG-V15|'
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']
MAX_DOWNLOAD=25_000_000
MAX_DECOMPRESSED=120_000_000

def read_selected(path):
    with open(path,newline='') as f:return list(csv.DictReader(f))

def frozen_select(rows,seen):
    cand=[r for r in rows if r['hash'] not in seen]
    cand.sort(key=lambda r: hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest())
    return cand[:N_SELECT]

def normalize(data):
    codec='plain'
    if data.startswith(b'\xfd7zXZ\x00'):
        codec='xz'; raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):
        codec='gzip'; raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):
        codec='bzip2'; raw=bz2.decompress(data)
    else: raw=data
    if len(raw)>MAX_DECOMPRESSED:raise ValueError('decompressed_too_large')
    # Require textual DIMACS after normalization. Leading comments are fine.
    head=raw[:1_000_000].decode('ascii','ignore')
    if not any(line.startswith('p cnf ') for line in head.splitlines()):raise ValueError('no_dimacs_header_after_normalization')
    return raw,codec

def download(row,out):
    url='https://benchmark-database.de/file/'+row['hash']
    try:
        with urllib.request.urlopen(url,timeout=35) as f:data=f.read(MAX_DOWNLOAD+1)
        if len(data)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(data)}
        raw,codec=normalize(data);out.write_bytes(raw)
        return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'codec':codec,'sha256_download':hashlib.sha256(data).hexdigest(),'sha256_cnf':hashlib.sha256(raw).hexdigest()}
    except Exception as e:return {'download':'failed','error':str(e)}

def parse_model(text):
    m={}
    for line in text.splitlines():
        if not line.startswith('v '):continue
        for tok in line[2:].split():
            try:x=int(tok)
            except:continue
            if x:m[abs(x)]=x>0
    return m

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

def verify_model(path,m):
    return all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def run(cmd,timeout,path=None):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'ERROR'
    ok=''
    if st=='SAT' and path is not None:ok=verify_model(path,parse_model(p.stdout))
    return {'status':st,'wall_s':wall,'model_ok':ok}

def run_v15(binpath,path,kissat,cms):
    t=time.perf_counter()
    try:p=subprocess.run([binpath,str(path),'--kissat',kissat,'--cms',cms,'--budget-ms',str(int(TIMEOUT*1000)),'--pre-ms',str(PRE_MS),'--mixed-ms',str(MIXED_MS)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+1)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'route':'outer-timeout','model_ok':''}
    wall=time.perf_counter()-t
    try:d=json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:return {'status':'ERROR','wall_s':wall,'route':'parse-error','model_ok':'','raw':p.stdout[-1000:]}
    return {'status':d.get('status'),'wall_s':wall,'route':d.get('route'),'model_ok':d.get('model_ok',''),
            'sample_s':d.get('sample_s'),'short_frac':d.get('short_frac'),'dup_frac':d.get('dup_frac'),
            'equations':d.get('equations'),'internal_frac':d.get('internal_frac'),'output_ratio':d.get('output_ratio')}

def main():
    root=Path('v15_eval');root.mkdir(exist_ok=True)
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/selected_benchmarks.csv',root/'selected_benchmarks.csv')
    seen={x.strip() for x in Path('v15_seen_hashes.txt').read_text().splitlines() if x.strip()}
    chosen=frozen_select(read_selected(root/'selected_benchmarks.csv'),seen)
    with open(root/'frozen_selection.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['rank','hash','author','family','result','selection_digest']);w.writeheader()
        for i,r in enumerate(chosen):w.writerow({'rank':i,'hash':r['hash'],'author':r['author'],'family':r['family'],'result':r['result'],'selection_digest':hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest()})
    rows=[]; receipts=[]
    kissat=os.environ['KISSAT'];cms=os.environ['CMS'];v15=os.environ['V15']
    for rank,r in enumerate(chosen):
        p=root/(r['hash']+'.cnf');rec={'rank':rank,**r,**download(r,p)};receipts.append(rec);print('DOWNLOAD',json.dumps(rec),flush=True)
        if rec['download']!='ok':continue
        variants=['kissat','cms','v15'];random.Random(int(r['hash'][:16],16)^0x515151).shuffle(variants)
        for v in variants:
            if v=='kissat':res=run([kissat,'--quiet','--seed=0',str(p)],TIMEOUT,p)
            elif v=='cms':res=run([cms,*CMS_OPTS,str(p)],TIMEOUT,p)
            else:res=run_v15(v15,p,kissat,cms)
            row={'rank':rank,'hash':r['hash'],'family':r['family'],'known':r['result'],'variant':v,**res};rows.append(row);print('ROW',json.dumps(row),flush=True)
    Path(root/'download_receipts.json').write_text(json.dumps(receipts,indent=2))
    fields=sorted({k for r in rows for k in r})
    with open(root/'results.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    bad=[];byhash={}
    for r in rows:
        if r.get('status')=='SAT' and r.get('model_ok') is False:bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r.get('status').lower()!=r['known']:bad.append({'type':'known_mismatch',**r})
        byhash.setdefault(r['hash'],[]).append(r)
    for h,rs in byhash.items():
        solved={r['status'] for r in rs if r.get('status') in ('SAT','UNSAT')}
        if len(solved)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(solved)})
    Path(root/'validation.json').write_text(json.dumps({'bad':bad,'n_bad':len(bad)},indent=2))
    print('VALIDATION',json.dumps({'n_bad':len(bad),'bad':bad[:4]}),flush=True)
    if bad:sys.exit(2)

if __name__=='__main__':main()
