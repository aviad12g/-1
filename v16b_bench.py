#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path
from v16b_affine_substitute_xnf import transform,reconstruct,parse_xnf_assignment

TIMEOUT=10.0

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>160_000_000:raise ValueError('too_large_after_decompress')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(35_000_001)
    if len(data)>35_000_000:raise ValueError('too_large_download')
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

def verify(path,a):
    return all(any((l>0)==bool(a[abs(l)]) for l in c) for c in iter_cnf(path))

def run_xorricane(binpath,xnf,cnf,mapping,meta,args):
    t=time.perf_counter()
    try:p=subprocess.run([binpath,'-vb','0','-t',str(int(TIMEOUT)),*args,str(xnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+2)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','solver_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else ('TIMEOUT' if p.returncode==0 else 'ERROR')
    ok=''
    if st=='SAT':
        fa,seen=parse_xnf_assignment(p.stdout,meta['free_vars'])
        full=reconstruct(mapping,fa);ok=verify(cnf,full)
    return {'status':st,'solver_s':wall,'model_ok':ok,'returncode':p.returncode,'raw_tail':p.stdout[-500:] if st=='ERROR' else ''}

def main():
    root=Path('v16b');root.mkdir(exist_ok=True)
    rows=list(csv.DictReader(open('v15_nearmiss_candidates.csv')));xorricane=os.environ['XORRICANE'];out=[];receipts=[]
    configs={
      'xnf_sub_default':[],
      'xnf_sub_ip_full':['-ip','full'],
      'xnf_sub_il16':['-il','16'],
      'xnf_sub_full_il16':['-ip','full','-il','16'],
    }
    for r in rows:
        cnf=root/(r['hash']+'.cnf');xnf=root/(r['hash']+'.xnf')
        rec={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'struct_score':r['struct_score']}
        try:
            db,rb,sha=download(r['hash'],cnf);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,sha256_cnf=sha)
            t=time.perf_counter();meta,mapping=transform(cnf,xnf);transform_s=time.perf_counter()-t;rec.update(meta);rec['transform_s']=transform_s
        except Exception as e:
            rec.update(download='failed',error=str(e));receipts.append(rec);continue
        receipts.append(rec);print('TRANSFORM',json.dumps(rec),flush=True)
        if meta['status']=='UNSAT':
            out.append({**rec,'variant':'transform_direct','status':'UNSAT','solver_s':0.0,'total_s':transform_s,'model_ok':''});continue
        names=list(configs);random.Random(int(r['hash'][:16],16)^0x16B16B).shuffle(names)
        for name in names:
            res=run_xorricane(xorricane,xnf,cnf,mapping,meta,configs[name]);row={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'struct_score':r['struct_score'],'variant':name,'transform_s':transform_s,'free_vars':meta['free_vars'],'var_reduction':meta['var_reduction'],'xnf_clauses':meta['xnf_clauses'],'clause_reduction':meta['clause_reduction'],'avg_lineral_terms':meta['avg_lineral_terms'],'max_lineral_terms':meta['max_lineral_terms'],**res};row['total_s']=transform_s+res['solver_s'];out.append(row);print('ROW',json.dumps(row),flush=True)
        cnf.unlink(missing_ok=True);xnf.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2));fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and str(r.get('model_ok')).lower()=='false':bad.append({'type':'invalid_model',**r})
        if r['known'] in ('sat','unsat') and r.get('status') in ('SAT','UNSAT') and r['known']!=r['status'].lower():bad.append({'type':'known_mismatch',**r})
    for h in {r['hash'] for r in out}:
        ss={r['status'] for r in out if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'n_bad':len(bad),'bad':bad},indent=2));print('VALIDATION',json.dumps({'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
