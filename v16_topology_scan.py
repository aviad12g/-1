#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,math,urllib.request
from pathlib import Path
from collections import defaultdict,deque

MAX_DOWNLOAD=35_000_000; MAX_RAW=180_000_000
DATAPATH=[
'e685a5d96e1ee9e051f191eca84b0d88',
'12535b3264a9c88bac14522171b497ef',
'2a38c5d48846ee1c35c4c40938082a16',
'211b0708454f7901054f5f92f525972e',
'5ab5ac8d66c7e375037f12a536baf721',
'27495ba0093076d2e39a9b218e521ee2',
]

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
    raw=normalize(data);p.write_bytes(raw);return len(raw),hashlib.sha256(raw).hexdigest()

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
    groups=defaultdict(int);idxs=defaultdict(list)
    for i,c in enumerate(clauses):
        kp=keypat(c)
        if kp:
            key,pat=kp;groups[key]|=1<<pat;idxs[(key,pat)].append(i)
    eq=[];covered=set()
    for key,bits in groups.items():
        em,om=pmask(len(key),0),pmask(len(key),1);he=(bits&em)==em;ho=(bits&om)==om
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
    gates=[];seen=set();covered=set()
    for ti,c in enumerate(clauses):
        if len(c)!=3 or len({abs(x) for x in c})<3:continue
        for k in range(3):
            out=c[k];a=c[(k+1)%3];b=c[(k+2)%3]
            q1=norm_clause((-a,-out));q2=norm_clause((-b,-out))
            if q1 in binmap and q2 in binmap:
                ins=tuple(sorted((-a,-b),key=lambda x:(abs(x),x<0)));gate=(out,ins)
                if gate in seen:continue
                seen.add(gate);gates.append(gate);covered.add(ti);covered.add(binmap[q1][0]);covered.add(binmap[q2][0])
    return gates,covered

class DSU:
    def __init__(self,n):self.p=list(range(n+1));self.sz=[1]*(n+1)
    def find(self,x):
        while self.p[x]!=x:self.p[x]=self.p[self.p[x]];x=self.p[x]
        return x
    def union(self,a,b):
        a=self.find(a);b=self.find(b)
        if a==b:return
        if self.sz[a]<self.sz[b]:a,b=b,a
        self.p[b]=a;self.sz[a]+=self.sz[b]

def tarjan(adj):
    n=len(adj);idx=0;stack=[];on=[False]*n;I=[-1]*n;L=[0]*n;scc=[]
    def dfs(v):
        nonlocal idx
        I[v]=L[v]=idx;idx+=1;stack.append(v);on[v]=True
        for w in adj[v]:
            if I[w]<0:dfs(w);L[v]=min(L[v],L[w])
            elif on[w]:L[v]=min(L[v],I[w])
        if L[v]==I[v]:
            c=[]
            while True:
                w=stack.pop();on[w]=False;c.append(w)
                if w==v:break
            scc.append(c)
    for v in range(n):
        if I[v]<0:dfs(v)
    return scc

def analyze(n,clauses):
    xors,xc=recover_xor(clauses);gates,gc=recover_and_gates(clauses)
    d=DSU(n);affine=set()
    for key,_ in xors:
        affine.update(key)
        for v in key[1:]:d.union(key[0],v)
    compvars=defaultdict(set)
    for v in affine:compvars[d.find(v)].add(v)
    roots=list(compvars);rid={r:i for i,r in enumerate(roots)}
    vcomp={v:rid[d.find(v)] for v in affine}
    boundary=set();uncovered=set(range(len(clauses)))-xc
    for i in uncovered:
        for l in clauses[i]:
            if abs(l) in affine:boundary.add(abs(l))
    comp_boundary=defaultdict(set)
    for v in boundary:comp_boundary[vcomp[v]].add(v)
    internal_total=sum(len(vs-comp_boundary[i]) for i,vs in enumerate(compvars[r] for r in roots))
    comp_sizes=[len(compvars[r]) for r in roots];bwidth=[len(comp_boundary[i]) for i in range(len(roots))]
    # Skeleton nodes = XOR components plus one singleton node per non-affine variable touched by a gate.
    nextid=len(roots);singleton={}
    def node(v):
        nonlocal nextid
        if v in vcomp:return vcomp[v]
        if v not in singleton:singleton[v]=nextid;nextid+=1
        return singleton[v]
    edges=set();internal_gates=0;cross_gates=0
    for out,ins in gates:
        o=node(abs(out));ii=[node(abs(x)) for x in ins]
        if all(x==o for x in ii):internal_gates+=1
        else:cross_gates+=1
        for x in ii:
            if x!=o:edges.add((x,o))
    adj=[set() for _ in range(nextid)]
    for a,b in edges:adj[a].add(b)
    scc=tarjan(adj);sid={v:i for i,c in enumerate(scc) for v in c};cyc=sum(len(c) for c in scc if len(c)>1)
    selfcyc=sum(1 for a,b in edges if a==b)
    cadj=[set() for _ in scc];ind=[0]*len(scc)
    for a,b in edges:
        x,y=sid[a],sid[b]
        if x!=y and y not in cadj[x]:cadj[x].add(y);ind[y]+=1
    q=deque(i for i,dg in enumerate(ind) if dg==0);dist=[0]*len(scc);seen=0
    while q:
        u=q.popleft();seen+=1
        for v in cadj[u]:dist[v]=max(dist[v],dist[u]+1);ind[v]-=1; q.append(v) if ind[v]==0 else None
    semantic=xc|gc
    return {
      'n':n,'m':len(clauses),'xor_equations':len(xors),'and_gates':len(gates),
      'semantic_fraction':len(semantic)/max(1,len(clauses)),
      'affine_vars':len(affine),'affine_var_fraction':len(affine)/max(1,n),
      'xor_components':len(roots),'largest_xor_component':max(comp_sizes,default=0),
      'largest_xor_component_fraction':max(comp_sizes,default=0)/max(1,n),
      'median_xor_component':sorted(comp_sizes)[len(comp_sizes)//2] if comp_sizes else 0,
      'max_boundary_width':max(bwidth,default=0),'median_boundary_width':sorted(bwidth)[len(bwidth)//2] if bwidth else 0,
      'affine_internal_vars':internal_total,'affine_internal_fraction':internal_total/max(1,n),
      'skeleton_nodes':nextid,'skeleton_edges':len(edges),'cross_gates':cross_gates,'internal_gates':internal_gates,
      'scc_count':len(scc),'largest_scc':max((len(c) for c in scc),default=0),'cyclic_node_fraction':cyc/max(1,nextid),
      'condensation_depth':max(dist,default=0),'source_sccs':sum(1 for x in ind if x==0),
    }

def main():
    root=Path('v16_topology');root.mkdir(exist_ok=True);out=[]
    for h in DATAPATH:
        p=root/(h+'.cnf');rec={'hash':h}
        try:
            rec['cnf_bytes'],rec['sha256_cnf']=download(h,p);n,clauses=parse(p);rec.update(analyze(n,clauses))
        except Exception as e:rec['error']=str(e)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'topology.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
