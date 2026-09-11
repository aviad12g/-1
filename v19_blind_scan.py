#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,sys,urllib.request
from pathlib import Path
sys.setrecursionlimit(1_000_000)
from v17_topology import parse, analyze
from v19_router import route, RULE_TEXT

PREFIX='SAT-RAG-V19|'
N_CHOSEN=300
MAX_DOWNLOAD=25_000_000
MAX_RAW=120_000_000


def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('decompressed_too_large')
    if b'p cnf ' not in raw[:1_000_000]:raise ValueError('no_dimacs_header')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=35) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(data)}
    raw=normalize(data);p.write_bytes(raw)
    return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'sha256_cnf':hashlib.sha256(raw).hexdigest()}

def read_pool(path):
    lines=Path(path).read_text().splitlines();hdr=lines[0].split();out=[]
    for line in lines[1:]:
        p=line.split()
        if len(p)!=len(hdr):continue
        out.append(dict(zip(hdr,p)))
    return out

def main():
    shard=int(os.environ.get('SHARD','0'));nshards=int(os.environ.get('NSHARDS','10'));root=Path('v19_blind');root.mkdir(exist_ok=True)
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/benchmarks2026.csv',root/'benchmarks2026.csv')
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/selected_benchmarks.csv',root/'selected.csv')
    pool=read_pool(root/'benchmarks2026.csv');selected={r['hash'] for r in csv.DictReader(open(root/'selected.csv'))};seen={x.strip() for x in Path('v15_seen_hashes.txt').read_text().splitlines() if x.strip()}
    candidates=[r for r in pool if r.get('participates')=='yes' and r['hash'] not in selected and r['hash'] not in seen]
    candidates.sort(key=lambda r:hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest());chosen=candidates[:N_CHOSEN]
    out=[]
    for rank,r in enumerate(chosen):
        if rank%nshards!=shard:continue
        h=r['hash'];p=root/(h+'.cnf');rec={'v19_rank':rank,'hash':h,'author':r['author'],'family':r['family'],'known':r['result'],'selection_digest':hashlib.sha256((PREFIX+h).encode()).hexdigest(),'v19_rule':RULE_TEXT,'pool':'2026 submitted participates=yes excluding all selected benchmarks'}
        try:
            rec.update(download(h,p))
            if rec['download']=='ok':
                n,clauses=parse(p);d=analyze(n,clauses);rec.update({k:v for k,v in d.items() if k!='components_json'});sel,diag=route(d);rec.update(diag)
        except Exception as e:rec.update(download='failed',error=str(e),v19_route=False)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    Path(root/f'meta_{shard}.json').write_text(json.dumps({'pool_size':len(candidates),'chosen':len(chosen),'shard':shard,'nshards':nshards},indent=2))
if __name__=='__main__':main()
