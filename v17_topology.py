#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,statistics,urllib.request
from pathlib import Path
from collections import defaultdict, Counter, deque

MAX_DOWNLOAD=35_000_000
MAX_RAW=180_000_000
MAXK=6

class UF:
    def __init__(self,n): self.p=list(range(n+1)); self.sz=[1]*(n+1)
    def find(self,x):
        p=self.p
        while p[x]!=x:
            p[x]=p[p[x]]; x=p[x]
        return x
    def union(self,a,b):
        a=self.find(a); b=self.find(b)
        if a==b:return a
        if self.sz[a]<self.sz[b]:a,b=b,a
        self.p[b]=a; self.sz[a]+=self.sz[b]
        return a

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'): raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'): raw=gzip.decompress(data)
    elif data.startswith(b'BZh'): raw=bz2.decompress(data)
    else: raw=data
    if len(raw)>MAX_RAW: raise ValueError('too_large_raw')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD: raise ValueError('too_large_download')
    raw=normalize(data);p.write_bytes(raw)
    return {'download_bytes':len(data),'cnf_bytes':len(raw),'sha256_cnf':hashlib.sha256(raw).hexdigest()}

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
    if not(1<=len(c)<=MAXK):return None
    a=sorted((abs(l),l<0) for l in c)
    if any(a[i][0]==a[i-1][0] for i in range(1,len(a))):return None
    return tuple(v for v,_ in a),sum((1<<i) for i,(_,neg) in enumerate(a) if neg)

def pmask(k,p):return sum((1<<x) for x in range(1<<k) if (x.bit_count()&1)==p)

def recover_xor(clauses):
    groups=defaultdict(int);idxs=defaultdict(list)
    for i,c in enumerate(clauses):
        kp=keypat(c)
        if kp:
            key,pat=kp;groups[key]|=1<<pat;idxs[(key,pat)].append(i)
    eq=[];covered=set();contradictions=0
    for key,bits in groups.items():
        em,om=pmask(len(key),0),pmask(len(key),1);he=(bits&em)==em;ho=(bits&om)==om
        if he and ho:contradictions+=1;continue
        if he or ho:
            forbidden=0 if he else 1;rhs=1 if he else 0;eq.append((key,rhs))
            for pat in range(1<<len(key)):
                if (pat.bit_count()&1)==forbidden:covered.update(idxs.get((key,pat),[]))
    return eq,covered,contradictions

def norm_clause(c):return tuple(sorted(c,key=lambda x:(abs(x),x<0)))

def recover_and_gates(clauses):
    binmap=defaultdict(list)
    for i,c in enumerate(clauses):
        if len(c)==2 and abs(c[0])!=abs(c[1]):binmap[norm_clause(c)].append(i)
    gates=[];seen=set();covered=set()
    for ti,c in enumerate(clauses):
        if len(c)!=3 or len({abs(x) for x in c})<3:continue
        for k in range(3):
            out=c[k];a=c[(k+1)%3];b=c[(k+2)%3];q1=norm_clause((-a,-out));q2=norm_clause((-b,-out))
            if q1 in binmap and q2 in binmap:
                ins=tuple(sorted((-a,-b),key=lambda x:(abs(x),x<0)));gate=(out,ins)
                if gate in seen:continue
                seen.add(gate);gates.append(gate);covered.add(ti);covered.add(binmap[q1][0]);covered.add(binmap[q2][0])
    return gates,covered

def gf2_rank(rows,cols=None):
    if not rows:return 0
    if cols is None:pos={v:i for i,v in enumerate(sorted({v for r in rows for v in r}))}
    else:pos={v:i for i,v in enumerate(cols)}
    basis={};rank=0
    for rr in rows:
        x=0
        for v in rr:
            j=pos.get(v)
            if j is not None:x^=1<<j
        while x:
            p=x.bit_length()-1
            if p in basis:x^=basis[p]
            else:basis[p]=x;rank+=1;break
    return rank

def tarjan(adj):
    n=len(adj);index=0;stack=[];on=[False]*n;idx=[-1]*n;low=[0]*n;comps=[]
    def dfs(v):
        nonlocal index
        idx[v]=low[v]=index;index+=1;stack.append(v);on[v]=True
        for w in adj[v]:
            if idx[w]<0:dfs(w);low[v]=min(low[v],low[w])
            elif on[w]:low[v]=min(low[v],idx[w])
        if low[v]==idx[v]:
            c=[]
            while True:
                w=stack.pop();on[w]=False;c.append(w)
                if w==v:break
            comps.append(c)
    for v in range(n):
        if idx[v]<0:dfs(v)
    return comps

def longest_dag_path(adj,comp_id,ncomp):
    dag=[set() for _ in range(ncomp)];ind=[0]*ncomp
    for v,outs in enumerate(adj):
        a=comp_id[v]
        for w in outs:
            b=comp_id[w]
            if a!=b and b not in dag[a]:dag[a].add(b);ind[b]+=1
    q=deque(i for i,d in enumerate(ind) if d==0);dist=[0]*ncomp
    while q:
        a=q.popleft()
        for b in dag[a]:
            dist[b]=max(dist[b],dist[a]+1);ind[b]-=1
            if ind[b]==0:q.append(b)
    return max(dist,default=0),sum(len(x) for x in dag)

def analyze(n,clauses):
    xors,xc,xcontra=recover_xor(clauses);gates,gc=recover_and_gates(clauses);semantic=xc|gc
    residual=[(i,c) for i,c in enumerate(clauses) if i not in semantic]
    uf=UF(n);xor_vars=set();xordeg=Counter()
    for key,rhs in xors:
        xor_vars.update(key)
        for v in key:xordeg[v]+=1
        if key:
            for b in key[1:]:uf.union(key[0],b)
    comp_vars=defaultdict(set);comp_eqs=defaultdict(list)
    for v in xor_vars:comp_vars[uf.find(v)].add(v)
    for key,rhs in xors:
        if key:comp_eqs[uf.find(key[0])].append(key)
    gate_vars=set(abs(x) for out,ins in gates for x in (out,*ins));residual_vars=set(abs(l) for _,c in residual for l in c);boundary_vars=gate_vars|residual_vars
    comps=[]
    for root,vs in comp_vars.items():
        eqrows=comp_eqs[root];b=sorted(vs&boundary_vars);internal=sorted(vs-boundary_vars);rank_total=gf2_rank(eqrows);rank_internal=gf2_rank(eqrows,internal) if internal else 0
        comps.append({'root':root,'vars':len(vs),'eqs':len(eqrows),'rank':rank_total,'boundary':len(b),'internal':len(internal),'boundary_rank':rank_total-rank_internal,'deficiency':len(vs)-rank_total})
    comps.sort(key=lambda x:x['vars'],reverse=True)
    roots=sorted(comp_vars);root_to_mod={r:i for i,r in enumerate(roots)};var_mod={v:root_to_mod[uf.find(v)] for v in xor_vars};nextmod=len(roots)
    for v in sorted(gate_vars-xor_vars):var_mod[v]=nextmod;nextmod+=1
    nmods=nextmod;madj=[set() for _ in range(nmods)];gate_self=gate_cross=0
    for out,ins in gates:
        om=var_mod.get(abs(out))
        if om is None:continue
        for il in ins:
            im=var_mod.get(abs(il))
            if im is None:continue
            madj[im].add(om)
            if im==om:gate_self+=1
            else:gate_cross+=1
    scc=tarjan(madj) if nmods else [];cid=[0]*nmods
    for i,c in enumerate(scc):
        for v in c:cid[v]=i
    dag_depth,dag_edges=longest_dag_path(madj,cid,len(scc)) if nmods else (0,0);nontriv=[c for c in scc if len(c)>1 or (len(c)==1 and c[0] in madj[c[0]])];cyc_nodes=sum(len(c) for c in nontriv)
    cross_res=one_res=0;mod_card=[]
    for _,c in residual:
        mods={var_mod[abs(l)] for l in c if abs(l) in var_mod};mod_card.append(len(mods))
        if len(mods)>1:cross_res+=1
        elif len(mods)==1:one_res+=1
    comp_sizes=[c['vars'] for c in comps];internal4=sum(c['internal'] for c in comps if c['boundary']<=4);internal8=sum(c['internal'] for c in comps if c['boundary']<=8);internal16=sum(c['internal'] for c in comps if c['boundary']<=16);projected=sum(c['boundary_rank'] for c in comps);internal=sum(c['internal'] for c in comps);largest=comps[0] if comps else {'vars':0,'eqs':0,'rank':0,'boundary':0,'internal':0,'boundary_rank':0};deg=[xordeg[v] for v in xor_vars]
    return {'n':n,'m':len(clauses),'xor_equations':len(xors),'and_gates':len(gates),'xor_contradictions':xcontra,'semantic_fraction':len(semantic)/max(1,len(clauses)),'residual_clauses':len(residual),'xor_vars':len(xor_vars),'xor_var_fraction':len(xor_vars)/max(1,n),'xor_components':len(comps),'largest_xor_comp_vars':largest['vars'],'largest_xor_comp_frac':largest['vars']/max(1,n),'largest_xor_comp_eqs':largest['eqs'],'largest_xor_comp_rank':largest['rank'],'largest_xor_comp_boundary':largest['boundary'],'largest_xor_comp_internal':largest['internal'],'largest_xor_comp_boundary_rank':largest['boundary_rank'],'affine_internal_vars':internal,'affine_internal_frac':internal/max(1,n),'projected_boundary_rank_sum':projected,'projected_rank_per_xor':projected/max(1,len(xors)),'internal_small_boundary4_frac':internal4/max(1,n),'internal_small_boundary8_frac':internal8/max(1,n),'internal_small_boundary16_frac':internal16/max(1,n),'xor_component_median_vars':statistics.median(comp_sizes) if comp_sizes else 0,'xor_component_max_boundary_ratio':max((c['boundary']/max(1,c['vars']) for c in comps),default=0),'xor_degree_mean':statistics.mean(deg) if deg else 0,'xor_degree_max':max(deg,default=0),'semantic_modules':nmods,'gate_edges_cross':gate_cross,'gate_edges_self':gate_self,'gate_scc_count':len(scc),'gate_nontrivial_scc_count':len(nontriv),'gate_cyclic_module_frac':cyc_nodes/max(1,nmods),'gate_largest_scc_frac':max((len(c) for c in scc),default=0)/max(1,nmods),'gate_condensation_depth':dag_depth,'gate_condensation_edges':dag_edges,'residual_cross_module_frac':cross_res/max(1,len(residual)),'residual_one_module_frac':one_res/max(1,len(residual)),'residual_module_card_mean':statistics.mean(mod_card) if mod_card else 0,'residual_module_card_max':max(mod_card,default=0),'components_json':json.dumps(comps[:20],separators=(',',':'))}

def main():
    rows=list(csv.DictReader(open('v15_nearmiss_candidates.csv')));root=Path('v17_topology');root.mkdir(exist_ok=True);out=[]
    for r in rows:
        p=root/(r['hash']+'.cnf');rec=dict(r)
        try:rec.update(download(r['hash'],p));n,clauses=parse(p);rec.update(analyze(n,clauses))
        except Exception as e:rec['error']=str(e)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'topology.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
