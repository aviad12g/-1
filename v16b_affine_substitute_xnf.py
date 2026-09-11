#!/usr/bin/env python3
import argparse, collections, json
from pathlib import Path

MAXK=6

def parse_cnf(path):
    n=None;clauses=[];cur=[]
    with open(path,errors='ignore') as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('c'):continue
            if s.startswith('p '):
                p=s.split()
                if len(p)>=4 and p[1]=='cnf':n=int(p[2])
                continue
            if s.startswith('%'):break
            for tok in s.split():
                x=int(tok)
                if x:cur.append(x)
                else:clauses.append(tuple(cur));cur=[]
    if cur:clauses.append(tuple(cur))
    if n is None:raise ValueError('missing p cnf header')
    return n,clauses

def key_pattern(c):
    if not (1<=len(c)<=MAXK):return None
    a=sorted((abs(l),l<0) for l in c)
    if any(a[i][0]==a[i-1][0] for i in range(1,len(a))):return None
    return tuple(v for v,_ in a),sum((1<<i) for i,(_,neg) in enumerate(a) if neg)

def parity_mask(k,p):return sum((1<<x) for x in range(1<<k) if (x.bit_count()&1)==p)

def recover(clauses):
    groups=collections.OrderedDict();idx=collections.defaultdict(list)
    for i,c in enumerate(clauses):
        kp=key_pattern(c)
        if kp is None:continue
        key,pat=kp;groups[key]=groups.get(key,0)|(1<<pat);idx[(key,pat)].append(i)
    eq=[];covered=set()
    for key,bits in groups.items():
        em,om=parity_mask(len(key),0),parity_mask(len(key),1)
        he=(bits&em)==em;ho=(bits&om)==om
        if he and ho:return eq,covered,True
        if he or ho:
            forbidden=0 if he else 1;rhs=1 if he else 0
            eq.append((key,rhs))
            for pat in range(1<<len(key)):
                if (pat.bit_count()&1)==forbidden:covered.update(idx.get((key,pat),[]))
    return eq,covered,False

def gaussian_expressions(n,eqs):
    # Echelon basis, pivot = largest original variable in each row.
    basis={}
    for key,rhs in eqs:
        bits=0
        for v in key:bits ^= 1<<(v-1)
        r=rhs
        while bits:
            p=bits.bit_length() # 1-based variable id
            if p not in basis:
                basis[p]=(bits,r);break
            b,br=basis[p];bits^=b;r^=br
        if bits==0 and r:return None,None,None,True
    piv=set(basis);free=[v for v in range(1,n+1) if v not in piv]
    free_index={v:i for i,v in enumerate(free)}
    expr={} # original var -> (bitset over compressed free vars, constant)
    for v in free:expr[v]=(1<<free_index[v],0)
    # Largest-pivot rows contain only lower-numbered variables. Process ascending.
    for p in sorted(piv):
        bits,r=basis[p];eb=0;c=r;rest=bits & ~(1<<(p-1))
        while rest:
            q0=(rest & -rest).bit_length()-1;q=q0+1;rest&=rest-1
            qb,qc=expr[q];eb^=qb;c^=qc
        expr[p]=(eb,c)
    return basis,free,expr,False

def is_encoding_clause(i,covered):return i in covered

def lineral_token(bits,const):
    if not bits:return None
    vars=[];b=bits
    while b:
        j=(b & -b).bit_length()-1;b&=b-1;vars.append(j+1)
    if const:vars[0]=-vars[0]
    return '+'.join(map(str,vars))

def transform_clause(c,expr):
    vals=[];seen={}
    for lit in c:
        b,k=expr[abs(lit)]
        k ^= (1 if lit<0 else 0)
        if b==0:
            if k:return None # true lineral makes whole OR clause tautological
            continue # false lineral contributes nothing
        prev=seen.get(b)
        if prev is not None:
            if prev!=k:return None # e OR not e
            continue
        seen[b]=k;vals.append((b,k))
    if not vals:return [] # empty clause = contradiction
    return vals

def transform(input_path,output_path=None):
    n,clauses=parse_cnf(input_path);eqs,covered,local_unsat=recover(clauses)
    if local_unsat:
        meta={'status':'UNSAT','n_original':n,'m_original':len(clauses),'xor_equations':len(eqs),'reason':'contradictory-complete-xor-encodings'}
        if output_path:
            with open(output_path,'w') as f:f.write('p xnf 1 2\n1 0\n-1 0\n')
        return meta,None
    basis,free,expr,unsat=gaussian_expressions(n,eqs)
    if unsat:
        meta={'status':'UNSAT','n_original':n,'m_original':len(clauses),'xor_equations':len(eqs),'reason':'gaussian-contradiction'}
        if output_path:
            with open(output_path,'w') as f:f.write('p xnf 1 2\n1 0\n-1 0\n')
        return meta,None
    out=[];dropped_taut=0;empty=False;total_lineral_terms=0;max_lineral_terms=0
    for i,c in enumerate(clauses):
        if i in covered:continue
        tc=transform_clause(c,expr)
        if tc is None:dropped_taut+=1;continue
        if tc==[]:empty=True;break
        out.append(tc)
        for b,k in tc:
            sz=b.bit_count();total_lineral_terms+=sz;max_lineral_terms=max(max_lineral_terms,sz)
    if empty:
        meta={'status':'UNSAT','n_original':n,'m_original':len(clauses),'xor_equations':len(eqs),'rank':len(basis),'free_vars':len(free),'reason':'empty-clause-after-substitution'}
        if output_path:
            with open(output_path,'w') as f:f.write('p xnf 1 2\n1 0\n-1 0\n')
        return meta,{'free':free,'expr':expr}
    if output_path:
        with open(output_path,'w') as f:
            f.write(f'p xnf {max(1,len(free))} {len(out)}\n')
            for cl in out:
                f.write(' '.join(lineral_token(b,k) for b,k in cl)+' 0\n')
    meta={'status':'UNKNOWN','n_original':n,'m_original':len(clauses),'xor_equations':len(eqs),'xor_encoding_clauses_removed':len(covered),'rank':len(basis),'free_vars':len(free),'var_reduction':1-len(free)/max(1,n),'xnf_clauses':len(out),'clause_reduction':1-len(out)/max(1,len(clauses)),'dropped_tautologies':dropped_taut,'total_linerals':sum(len(c) for c in out),'total_lineral_terms':total_lineral_terms,'avg_lineral_terms':total_lineral_terms/max(1,sum(len(c) for c in out)),'max_lineral_terms':max_lineral_terms}
    return meta,{'free':free,'expr':expr}

def parse_xnf_assignment(text,k):
    a=[False]*(k+1);seen=set()
    for line in text.splitlines():
        if not line.startswith('v'):continue
        for tok in line[1:].split():
            try:x=int(tok)
            except:continue
            if not x:continue
            v=abs(x)
            if v<=k:a[v]=x>0;seen.add(v)
    return a,seen

def reconstruct(mapping,free_assignment):
    free=mapping['free'];expr=mapping['expr'];vals=[False]*(max(expr)+1 if expr else 1)
    bitvalue=0
    for i,v in enumerate(free):
        val=bool(free_assignment[i+1]);vals[v]=val
        if val:bitvalue|=1<<i
    for v,(b,c) in expr.items():
        vals[v]=bool(((b & bitvalue).bit_count()&1)^c)
    return vals

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('output');ap.add_argument('--meta')
    a=ap.parse_args();meta,_=transform(a.input,a.output)
    if a.meta:Path(a.meta).write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta))
if __name__=='__main__':main()
