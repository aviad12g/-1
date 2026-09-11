#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,urllib.request
from pathlib import Path
from v17_topology import parse, analyze

PREFIX='SAT-RAG-V15|'
START=150
STOP=350
MAX_DOWNLOAD=25_000_000
MAX_RAW=120_000_000

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('decompressed_too_large')
    head=raw[:1_000_000].decode('ascii','ignore')
    if not any(x.startswith('p cnf ') for x in head.splitlines()):raise ValueError('no_dimacs_header')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=35) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(data)}
    raw=normalize(data);p.write_bytes(raw)
    return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'sha256_cnf':hashlib.sha256(raw).hexdigest()}

def main():
    shard=int(os.environ.get('SHARD','0'));nshards=int(os.environ.get('NSHARDS','8'));root=Path('v17_blind');root.mkdir(exist_ok=True)
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/selected_benchmarks.csv',root/'selected.csv')
    rows=list(csv.DictReader(open(root/'selected.csv')));seen={x.strip() for x in Path('v15_seen_hashes.txt').read_text().splitlines() if x.strip()};cand=[r for r in rows if r['hash'] not in seen];cand.sort(key=lambda r:hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest());chosen=cand[START:STOP]
    out=[]
    for rank,r in enumerate(chosen,start=START):
        if rank % nshards != shard:continue
        p=root/(r['hash']+'.cnf');rec={'global_rank':rank,'hash':r['hash'],'author':r['author'],'family':r['family'],'known':r['result'],'selection_digest':hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest()}
        try:
            rec.update(download(r['hash'],p))
            if rec['download']=='ok':
                n,clauses=parse(p);d=analyze(n,clauses);rec.update({k:v for k,v in d.items() if k!='components_json'});rec['v17_route']=bool(d['largest_xor_comp_vars']>=1000 and d['gate_condensation_depth']>=4)
        except Exception as e:rec.update(download='failed',error=str(e),v17_route=False)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
