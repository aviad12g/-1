#!/usr/bin/env python3
import bz2,collections,gzip,hashlib,json,lzma,os,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert

# Exact hash from the frozen V19 validation artifact.
HASH='05bb70b8ddfd1fb36c6085d6427992a1'
MAXK=6

def norm(data):
    if data.startswith(b'\xfd7zXZ\x00'): return lzma.decompress(data)
    if data.startswith(b'\x1f\x8b'): return gzip.decompress(data)
    if data.startswith(b'BZh'): return bz2.decompress(data)
    return data

def parse_cnf(path):
    n=0; clauses=[];cur=[]
    for line in open(path,errors='ignore'):
        s=line.strip()
        if not s or s.startswith('c'):continue
        if s.startswith('p '):n=int(s.split()[2]);continue
        if s.startswith('%'):break
        for t in s.split():
            x=int(t)
            if x:cur.append(x)
            else:clauses.append(tuple(cur));cur=[]
    return n,clauses

def clause_pattern(c):
    if not (1<=len(c)<=MAXK):return None
    a=sorted((abs(x),x<0) for x in c)
    if len({v for v,_ in a})!=len(a):return None
    return tuple(v for v,_ in a), sum((1<<i) for i,(_,neg) in enumerate(a) if neg)

def parse_xor_token(tok):
    neg=tok.startswith('-');body=tok[1:] if neg else tok
    if '+' not in body:return None
    vs=tuple(sorted(int(x) for x in body.split('+')))
    return vs,(0 if neg else 1)

def independent_transform_check(cnf,xnf):
    n,clauses=parse_cnf(cnf); xor_eqs=[]; ordinary=[]
    for line in open(xnf):
        s=line.strip()
        if not s or s.startswith('c') or s.startswith('p '):continue
        toks=s.split(); assert toks[-1]=='0'; toks=toks[:-1]
        if len(toks)==1 and '+' in toks[0]:
            q=parse_xor_token(toks[0]); assert q; xor_eqs.append(q)
        else: ordinary.append(tuple(int(x) for x in toks))
    original=collections.Counter(clauses); removed=collections.Counter();checks=[]
    for key,rhs in xor_eqs:
        k=len(key); assert 2<=k<=MAXK; forbidden=[]
        for val in range(1<<k):
            if (val.bit_count()&1)==rhs:continue
            c=tuple((-v if ((val>>i)&1) else v) for i,v in enumerate(key))
            target=(key,sum((1<<i) for i,x in enumerate(c) if x<0))
            found=None
            for oc in original:
                if clause_pattern(oc)==target and original[oc]-removed[oc]>0:
                    found=oc;break
            if found is None:raise AssertionError(f'missing forbidden assignment clause {key=} {rhs=} {val=}')
            removed[found]+=1;forbidden.append(val)
        checks.append({'vars':key,'rhs':rhs,'forbidden_assignments':len(forbidden)})
    remaining=original-removed
    if remaining!=collections.Counter(ordinary):
        raise AssertionError(f'ordinary-clause multiset mismatch remaining={sum(remaining.values())} xnf={len(ordinary)}')
    return {'ok':True,'vars':n,'original_clauses':len(clauses),'xor_equations':len(xor_eqs),
            'removed_encoding_clauses':sum(removed.values()),'ordinary_clauses':len(ordinary),
            'max_xor_arity':max((len(k) for k,_ in xor_eqs),default=0),'equation_checks':checks[:20]}

def main():
    root=Path('v20_certify');root.mkdir(exist_ok=True);cnf=root/(HASH+'.cnf');xnf=root/(HASH+'.xnf')
    with urllib.request.urlopen('https://benchmark-database.de/file/'+HASH,timeout=40) as f:raw=norm(f.read())
    cnf.write_bytes(raw)
    t=time.perf_counter();meta=convert(cnf,xnf);conv=time.perf_counter()-t
    cert=independent_transform_check(cnf,xnf);cert.update(hash=HASH,cnf_sha256=hashlib.sha256(raw).hexdigest(),convert_s=conv,converter_meta=meta)
    (root/'transform_certificate.json').write_text(json.dumps(cert,indent=2))
    print('TRANSFORM_CERT',json.dumps({k:v for k,v in cert.items() if k!='equation_checks'}),flush=True)
    xorcle=os.environ['XORCLE'];checker=os.environ['XORCLE_CHECKER'];proof=root/(HASH+'.lrup')
    t=time.perf_counter()
    try:
        p=subprocess.run([xorcle,'--compact=false',f'--proof={proof}',str(xnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=600)
        solve_s=time.perf_counter()-t;status='UNSAT' if p.returncode==20 or 's UNSATISFIABLE' in p.stdout else 'SAT' if p.returncode==10 or 's SATISFIABLE' in p.stdout else 'OTHER'
    except subprocess.TimeoutExpired:
        solve_s=time.perf_counter()-t;status='TIMEOUT';p=None
    check={'hash':HASH,'status':status,'solve_s':solve_s,'proof_exists':proof.exists(),'proof_bytes':proof.stat().st_size if proof.exists() else 0,'verified':False}
    if status=='UNSAT' and proof.exists():
        q=time.perf_counter();c=subprocess.run(['python3',checker,str(xnf),str(proof)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=300);check['check_s']=time.perf_counter()-q;check['checker_rc']=c.returncode;check['checker_tail']=c.stdout[-4000:];check['verified']=(c.returncode==0)
    if p is not None:check['solver_tail']=p.stdout[-4000:]
    (root/'proof_result.json').write_text(json.dumps(check,indent=2));print('PROOF_RESULT',json.dumps({k:v for k,v in check.items() if not k.endswith('_tail')}),flush=True)
    if status=='UNSAT' and not check['verified']:raise SystemExit(2)
if __name__=='__main__':main()
