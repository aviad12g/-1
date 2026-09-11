#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,urllib.request
from pathlib import Path
from collections import defaultdict

MAX_DOWNLOAD=35_000_000;MAX_RAW=180_000_000

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('too_large_raw')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:raise ValueError('too_large_download')
    raw=normalize(data);p.write_bytes(raw);return len(raw)

def parse(path):
    n=0;clauses=[];cur=[]
    with open(path,errors='ignore') as f:
      for line in f:
        s=line.strip()
        if not s or s.startswith('c'):continue
        if s.startswith('p '):n=int(s.split()[2]);continue
        if s.startswith('%'):break
        for tok in s.split():
          x=int(tok)
          if x:cur.append(x)
          else:clauses.append(tuple(cur));cur=[]
    if cur:clauses.append(tuple(cur))
    return n,clauses

def keypat(c):
    if not(1<=len(c)<=6):return None
    a=sorted((abs(l),l<0) for l in c)
    if any(a[i][0]==a[i-1][0] for i in range(1,len(a))):return None
    return tuple(v for v,_ in a),sum((1<<i) for i,(_,neg) in enumerate(a) if neg)

def pmask(k,p):return sum((1<<x) for x in range(1<<k) if (x.bit_count()&1)==p)

def recover_xor(clauses):
    groups=defaultdict(int); idxs=defaultdict(list)
    for i,c in enumerate(clauses):
        kp=keypat(c)
        if kp:
            key,pat=kp;groups[key]|=1<<pat;idxs[(key,pat)].append(i)
    eq=[];covered=set()
    for key,bits in groups.items():
        em,om=pmask(len(key),0),pmask(len(key),1)
        he=(bits&em)==em;ho=(bits&om)==om
        if he and ho:continue
        if he or ho:
            forbidden=0 if he else 1;rhs=1 if he else 0;eq.append((key,rhs))
            for pat in range(1<<len(key)):
                if (pat.bit_count()&1)==forbidden:covered.update(idxs.get((key,pat),[]))
    return eq,covered

def norm_clause(c):return tuple(sorted(c,key=lambda x:(abs(x),x<0)))

def recover_and_gates(clauses):
    binmap=defaultdict(list)
    for i,c in enumerate(clauses):
        if len(c)==2 and abs(c[0])!=abs(c[1]):binmap[norm_clause(c)].append(i)
    gates=set();covered=set()
    for ti,c in enumerate(clauses):
        if len(c)!=3 or len({abs(x) for x in c})<3:continue
        for k in range(3):
            out=c[k];a=c[(k+1)%3];b=c[(k+2)%3]
            q1=norm_clause((-a,-out));q2=norm_clause((-b,-out))
            if q1 in binmap and q2 in binmap:
                # generalized literal gate: out_literal <-> ((-a) AND (-b))
                ins=tuple(sorted((-a,-b),key=lambda x:(abs(x),x<0)))
                gate=(out,ins)
                if gate in gates:continue
                gates.add(gate);covered.add(ti);covered.add(binmap[q1][0]);covered.add(binmap[q2][0])
    return gates,covered

def main():
    root=Path('v16_gate_scan');root.mkdir(exist_ok=True);out=[]
    for r in csv.DictReader(open('v15_nearmiss_candidates.csv')):
        p=root/(r['hash']+'.cnf')
        rec={'hash':r['hash'],'global_rank':r['global_rank'],'family':r['family'],'known':r['known'],'struct_score':r['struct_score']}
        try:
            rec['cnf_bytes']=download(r['hash'],p);n,clauses=parse(p);xors,xc=recover_xor(clauses);gates,gc=recover_and_gates(clauses);union=xc|gc
            rec.update(n=n,m=len(clauses),xor_equations=len(xors),xor_clause_coverage=len(xc),generalized_and_gates=len(gates),and_clause_coverage=len(gc),semantic_clause_coverage=len(union),semantic_fraction=len(union)/max(1,len(clauses)),semantic_vars=len(set(v for key,_ in xors for v in key)|set(abs(x) for out,ins in gates for x in (out,*ins))))
        except Exception as e:rec['error']=str(e)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'gate_scan.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
