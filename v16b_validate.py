#!/usr/bin/env python3
import itertools,random,tempfile
from pathlib import Path
from v16b_affine_substitute_xnf import transform,reconstruct

def xor_encoding(vars,rhs):
    out=[]
    # clause excludes each assignment whose XOR != rhs
    for vals in itertools.product([0,1],repeat=len(vars)):
        if (sum(vals)&1)==rhs:continue
        # clause false exactly on vals: x if val=0 else not x
        out.append(tuple(v if val==0 else -v for v,val in zip(vars,vals)))
    return out

def eval_cnf(clauses,a):
    return all(any((l>0)==bool(a[abs(l)]) for l in c) for c in clauses)

def parse_xnf(path):
    clauses=[]
    with open(path) as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('c') or s.startswith('p '):continue
            cl=[]
            for tok in s.split():
                if tok=='0':break
                cl.append(tuple(int(x) for x in tok.split('+')))
            clauses.append(cl)
    return clauses

def eval_xnf(clauses,a):
    for cl in clauses:
        sat=False
        for lin in cl:
            v=0
            for l in lin:v ^= int(((l>0)==bool(a[abs(l)])))
            if v:sat=True;break
        if not sat:return False
    return True

def write_cnf(path,n,clauses):
    with open(path,'w') as f:
        f.write(f'p cnf {n} {len(clauses)}\n')
        for c in clauses:f.write(' '.join(map(str,c))+' 0\n')

def brute(n,clauses):
    sols=[]
    for vals in itertools.product([0,1],repeat=n):
        a=[0]+list(vals)
        if eval_cnf(clauses,a):sols.append(a)
    return sols

def main():
    rng=random.Random(16021602);checked=0;routes={'unsat-transform':0,'reduced-sat':0,'reduced-unsat':0}
    with tempfile.TemporaryDirectory() as td:
      td=Path(td)
      for n in range(2,9):
        for case in range(60):
            clauses=[]
            # 0..3 exact XORs of arity up to min(4,n)
            for _ in range(rng.randrange(4)):
                k=rng.randint(1,min(4,n));vs=tuple(sorted(rng.sample(range(1,n+1),k)));rhs=rng.randrange(2)
                clauses.extend(xor_encoding(vs,rhs))
            # arbitrary residual CNF, including overlaps with XOR vars
            for _ in range(rng.randint(0,7)):
                k=rng.randint(1,min(3,n));vs=rng.sample(range(1,n+1),k);clauses.append(tuple(v if rng.randrange(2) else -v for v in vs))
            inp=td/'a.cnf';out=td/'a.xnf';write_cnf(inp,n,clauses)
            orig=brute(n,clauses);meta,mapping=transform(inp,out)
            if meta['status']=='UNSAT':
                assert not orig,(n,case,'transform said UNSAT but original SAT');routes['unsat-transform']+=1;checked+=1;continue
            xnf=parse_xnf(out);k=meta['free_vars'];red=[]
            for vals in itertools.product([0,1],repeat=k):
                fa=[False]+[bool(x) for x in vals]
                if eval_xnf(xnf,fa):
                    red.append(fa);full=reconstruct(mapping,fa)
                    assert eval_cnf(clauses,full),(n,case,'reconstruction failed')
            assert bool(red)==bool(orig),(n,case,len(orig),len(red),meta)
            routes['reduced-sat' if red else 'reduced-unsat']+=1;checked+=1
    print('validated',checked,routes)
    assert checked==420
if __name__=='__main__':main()
