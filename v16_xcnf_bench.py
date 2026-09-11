#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path
from v16_xcnf import convert
TIMEOUT=10.0
CMS_OPTS=['--verb=0','--threads=1','--presimp=1','--maxxormat=10000000','--maxmatrixrows=20000','--maxmatrixcols=20000','--xorfindtout=4000','--autodisablegauss=0']

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>160_000_000:raise ValueError('too_large_raw')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(35_000_001)
    if len(data)>35_000_000:raise ValueError('too_large_download')
    raw=normalize(data);p.write_bytes(raw);return len(raw)

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

def verify(path,m):return all(any(m.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def run(cms,path,orig):
    t=time.perf_counter()
    try:p=subprocess.run([cms,*CMS_OPTS,str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+1)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t;st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'ERROR';ok=verify(orig,parse_model(p.stdout)) if st=='SAT' else ''
    return {'status':st,'wall_s':wall,'model_ok':ok,'returncode':p.returncode}

def main():
    root=Path('v16_xcnf');root.mkdir(exist_ok=True);cms=os.environ['CMS'];rows=list(csv.DictReader(open('v15_nearmiss_candidates.csv')));out=[]
    for r in rows:
        cnf=root/(r['hash']+'.cnf');xcnf=root/(r['hash']+'.xcnf')
        try:download(r['hash'],cnf);t=time.perf_counter();meta=convert(cnf,xcnf);conv=time.perf_counter()-t
        except Exception as e:print('ERROR',r['hash'],e,flush=True);continue
        variants=['cms_original','cms_xcnf'];random.Random(int(r['hash'][:16],16)^0xC0DEC0DE).shuffle(variants)
        for v in variants:
            rr=run(cms,cnf if v=='cms_original' else xcnf,cnf);row={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'variant':v,'convert_s':conv,'xors':meta.get('xors'),'compression_ratio':meta.get('compression_ratio'),**rr};row['total_s']=rr['wall_s']+(conv if v=='cms_xcnf' else 0);out.append(row);print('ROW',json.dumps(row),flush=True)
        cnf.unlink(missing_ok=True);xcnf.unlink(missing_ok=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and str(r.get('model_ok')).lower()=='false':bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch',**r})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2));print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
