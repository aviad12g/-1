#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,random,subprocess,time,urllib.request
from pathlib import Path

TIMEOUT=15.0
MAX_K=64

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>180_000_000:raise ValueError('too_large_after_decompress')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:d=f.read(40_000_001)
    if len(d)>40_000_000:raise ValueError('too_large_download')
    raw=normalize(d);p.write_bytes(raw)
    return len(d),len(raw),hashlib.sha256(raw).hexdigest()

def iter_cnf(path):
    cur=[];n=None
    with open(path,errors='ignore') as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('c'):continue
            if s.startswith('p '):
                p=s.split();n=int(p[2]);continue
            if s.startswith('%'):break
            for tok in s.split():
                x=int(tok)
                if x:cur.append(x)
                else:yield tuple(cur);cur=[]
    if cur:raise ValueError('unterminated_clause')

def header_n(path):
    with open(path,errors='ignore') as f:
        for line in f:
            if line.startswith('p cnf '):return int(line.split()[2])
    raise ValueError('missing_header')

def ckey(c):return tuple(sorted(c))
def pkey(a,b):return (a,b) if a<b else (b,a)

def discover_exactly_one(path):
    pairs=set();alos=set();m=0
    for c in iter_cnf(path):
        m+=1
        if len(c)==2:pairs.add(pkey(c[0],c[1]))
        elif 3<=len(c)<=MAX_K and len({abs(x) for x in c})==len(c):alos.add(ckey(c))
    groups=[];covered_pairs=set()
    for c in sorted(alos,key=lambda x:(-len(x),x)):
        req=[];ok=True
        for i in range(len(c)):
            for j in range(i+1,len(c)):
                k=pkey(-c[i],-c[j]);req.append(k)
                if k not in pairs:ok=False;break
            if not ok:break
        if ok:
            groups.append(c);covered_pairs.update(req)
    return groups,set(groups),covered_pairs,m

def opb_lit(l):return ('x' if l>0 else '~x')+str(abs(l))

def convert_to_opb(cnf,opb):
    n=header_n(cnf);t=time.perf_counter();groups,alos,pairs,m=discover_exactly_one(cnf)
    discovery=time.perf_counter()-t;t=time.perf_counter();residual=0;skipped=0
    with open(opb,'w') as o:
        o.write(f'* #variable= {n} #constraint= 0\n')
        o.write('* V22 exact structural transform: complete ALO + all pairwise AMO -> ExactlyOne\n')
        for c in iter_cnf(cnf):
            skip=(len(c)==2 and pkey(c[0],c[1]) in pairs) or (len(c)>=3 and ckey(c) in alos)
            if skip:skipped+=1;continue
            residual+=1;o.write(' '.join('+1 '+opb_lit(l) for l in c)+' >= 1;\n')
        for g in groups:o.write(' '.join('+1 '+opb_lit(l) for l in g)+' = 1;\n')
    write_s=time.perf_counter()-t
    return {'n':n,'original_clauses':m,'eo_groups':len(groups),'skipped_clause_occurrences':skipped,
            'residual_constraints':residual,'opb_constraints':residual+len(groups),
            'constraint_ratio':(residual+len(groups))/max(1,m),'discover_s':discovery,'write_s':write_s,
            'transform_s':discovery+write_s,'opb_bytes':opb.stat().st_size}

def parse_model(text,n):
    vals={}
    for line in text.splitlines():
        if not line.startswith('v'):continue
        for tok in line[1:].split():
            if tok.lstrip('-').isdigit():
                x=int(tok)
                if x:vals[abs(x)]=x>0
            elif tok.startswith('x') and tok[1:].isdigit(): vals[int(tok[1:])]=True
            elif tok.startswith('-x') and tok[2:].isdigit(): vals[int(tok[2:])]=False
    if not vals:return None
    return {i:vals.get(i,False) for i in range(1,n+1)}

def verify_cnf(path,model):
    if model is None:return False
    return all(any(model.get(abs(l),False)==(l>0) for l in c) for c in iter_cnf(path))

def run_kissat(bin,cnf):
    t=time.perf_counter()
    try:p=subprocess.run([bin,'--quiet','--seed=0',str(cnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+0.4)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','solve_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t;st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else ('TIMEOUT' if p.returncode in (0,124) else 'ERROR')
    return {'status':st,'solve_s':wall,'model_ok':'','returncode':p.returncode,'stdout_tail':p.stdout[-500:]}

def run_exact(bin,input_path,cnf,n):
    t=time.perf_counter()
    cmd=[bin,'--verbosity=0','--print-sol','--timeout='+str(TIMEOUT),str(input_path)]
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+0.8)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','solve_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t;txt=p.stdout
    if 's UNSATISFIABLE' in txt:st='UNSAT'
    elif 's SATISFIABLE' in txt or 's OPTIMUM FOUND' in txt:st='SAT'
    elif 's UNKNOWN' in txt or p.returncode==0:st='TIMEOUT'
    else:st='ERROR'
    ok=''
    if st=='SAT':ok=verify_cnf(cnf,parse_model(txt,n))
    return {'status':st,'solve_s':wall,'model_ok':ok,'returncode':p.returncode,'stdout_tail':txt[-800:]}

def self_test():
    # Exhaustively validate the logical replacement pattern on signed EO blocks k=3..5.
    import itertools
    for k in range(3,6):
        for signs in itertools.product([1,-1],repeat=k):
            lits=[signs[i]*(i+1) for i in range(k)]
            for bits in itertools.product([False,True],repeat=k):
                lt=[bits[abs(l)-1] if l>0 else not bits[abs(l)-1] for l in lits]
                original=(any(lt) and all(not(lt[i] and lt[j]) for i in range(k) for j in range(i+1,k)))
                native=(sum(lt)==1)
                if original!=native:raise AssertionError((k,signs,bits))
    return True

def main():
    assert self_test()
    root=Path('v22_pilot');root.mkdir(exist_ok=True);rows=list(csv.DictReader(open('v22_pilot_candidates.csv')))
    kissat=os.environ['KISSAT'];exact=os.environ['EXACT'];out=[];receipts=[]
    for r in rows:
        h=r['hash'];cnf=root/(h+'.cnf');opb=root/(h+'.opb');rec=dict(r)
        try:
            db,rb,sha=download(h,cnf);rec.update(download='ok',download_bytes=db,cnf_bytes=rb,actual_sha256=sha)
            if sha!=r['sha256_cnf']:raise ValueError('sha256_mismatch')
            meta=convert_to_opb(cnf,opb);rec.update(meta)
        except Exception as e:
            rec.update(download='failed',error=type(e).__name__+': '+str(e));receipts.append(rec);continue
        receipts.append(rec);print('TRANSFORM',json.dumps(rec),flush=True)
        variants=['kissat_cnf','exact_cnf','exact_eo_opb'];random.Random(int(h[:16],16)^0x22002200).shuffle(variants)
        for v in variants:
            if v=='kissat_cnf':res=run_kissat(kissat,cnf)
            elif v=='exact_cnf':res=run_exact(exact,cnf,cnf,meta['n'])
            else:
                res=run_exact(exact,opb,cnf,meta['n']);res['total_s']=meta['transform_s']+res['solve_s']
            row={**r,**{k:meta[k] for k in meta},'variant':v,**res};out.append(row);print('ROW',json.dumps(row),flush=True)
        cnf.unlink(missing_ok=True);opb.unlink(missing_ok=True)
    Path(root/'receipts.json').write_text(json.dumps(receipts,indent=2))
    fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    bad=[]
    for r in out:
        if r.get('status')=='SAT' and r['variant'].startswith('exact') and str(r.get('model_ok')).lower() not in ('true','1'):bad.append({'type':'invalid_model',**r})
    for h in {r['hash'] for r in out}:
        ss={r['status'] for r in out if r['hash']==h and r.get('status') in ('SAT','UNSAT')}
        if len(ss)>1:bad.append({'type':'solver_disagreement','hash':h,'statuses':sorted(ss)})
    Path(root/'validation.json').write_text(json.dumps({'self_test':True,'n_bad':len(bad),'bad':bad},indent=2))
    print('VALIDATION',json.dumps({'self_test':True,'n_bad':len(bad)}),flush=True)
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
