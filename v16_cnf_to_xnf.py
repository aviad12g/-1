#!/usr/bin/env python3
import argparse, collections, json
from pathlib import Path

MAXK=6

def parse_cnf(path):
    n=None; clauses=[]; cur=[]
    with open(path,errors='ignore') as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('c'): continue
            if s.startswith('p '):
                p=s.split();
                if len(p)>=4 and p[1]=='cnf': n=int(p[2])
                continue
            if s.startswith('%'): break
            for tok in s.split():
                x=int(tok)
                if x:cur.append(x)
                else:clauses.append(tuple(cur));cur=[]
    if cur:clauses.append(tuple(cur))
    if n is None: raise ValueError('missing p cnf header')
    return n,clauses

def key_pattern(c):
    if not (1 <= len(c) <= MAXK): return None
    a=sorted((abs(l),l<0) for l in c)
    if any(a[i][0]==a[i-1][0] for i in range(1,len(a))): return None
    key=tuple(v for v,_ in a); pat=sum((1<<i) for i,(_,neg) in enumerate(a) if neg)
    return key,pat

def parity_mask(k,par):
    return sum((1<<p) for p in range(1<<k) if (p.bit_count()&1)==par)

def recover(clauses):
    groups=collections.OrderedDict()
    for c in clauses:
        kp=key_pattern(c)
        if kp is None: continue
        key,pat=kp; groups[key]=groups.get(key,0)|(1<<pat)
    rec={}; eq_order=[]
    for key,bits in groups.items():
        em=parity_mask(len(key),0); om=parity_mask(len(key),1)
        he=(bits&em)==em; ho=(bits&om)==om
        if he and ho: return rec,eq_order,True
        if he: rec[key]=(0,1);eq_order.append(key)  # forbidden sign parity, XOR rhs
        elif ho: rec[key]=(1,0);eq_order.append(key)
    return rec,eq_order,False

def is_encoding_clause(c,rec):
    kp=key_pattern(c)
    if kp is None:return False
    key,pat=kp
    r=rec.get(key)
    return r is not None and (pat.bit_count()&1)==r[0]

def lineral(key,rhs):
    vals=list(key)
    toks=[]
    for i,v in enumerate(vals):
        toks.append(str(v if (rhs==1 or i>0) else -v))
    return '+'.join(toks)

def convert(inp,out):
    n,clauses=parse_cnf(inp);rec,order,contradiction=recover(clauses)
    if contradiction:
        # Simple contradictory XNF: x1 and not x1, preserving UNSAT.
        with open(out,'w') as f:f.write(f'p xnf {max(n,1)} 2\n1 0\n-1 0\n')
        return {'n':n,'original_clauses':len(clauses),'xors':len(order),'other_clauses':0,'xnf_clauses':2,'local_contradiction':True}
    other=[c for c in clauses if not is_encoding_clause(c,rec)]
    with open(out,'w') as f:
        f.write(f'p xnf {n} {len(order)+len(other)}\n')
        for key in order:
            f.write(lineral(key,rec[key][1])+' 0\n')
        for c in other:
            f.write(' '.join(map(str,c))+' 0\n')
    removed=len(clauses)-len(other)
    return {'n':n,'original_clauses':len(clauses),'xors':len(order),'xor_encoding_clauses_removed':removed,'other_clauses':len(other),'xnf_clauses':len(order)+len(other),'compression_ratio':(len(order)+len(other))/max(1,len(clauses)),'local_contradiction':False}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('output');ap.add_argument('--meta')
    a=ap.parse_args();d=convert(a.input,a.output)
    if a.meta:Path(a.meta).write_text(json.dumps(d,indent=2))
    print(json.dumps(d))
if __name__=='__main__':main()
