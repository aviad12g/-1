#!/usr/bin/env python3
import bz2,gzip,hashlib,json,lzma,os,re,sys,time,urllib.request,csv
from pathlib import Path
sys.setrecursionlimit(1_000_000)
from v17_topology import parse, analyze

PREFIX='SAT-RAG-V18-2025|'
N=96
MAX_DOWNLOAD=25_000_000
MAX_RAW=120_000_000
URI='https://raw.githubusercontent.com/satcompetition/2025/main/downloads/track_main_2025.uri'

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data);codec='xz'
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data);codec='gzip'
    elif data.startswith(b'BZh'):raw=bz2.decompress(data);codec='bzip2'
    else:raw=data;codec='plain'
    if len(raw)>MAX_RAW:raise ValueError('decompressed_too_large')
    head=raw[:1_000_000].decode('ascii','ignore')
    if not any(x.startswith('p cnf ') for x in head.splitlines()):raise ValueError('no_dimacs_header')
    return raw,codec

def benchmark_hashes():
    text=urllib.request.urlopen(URI,timeout=40).read().decode('utf-8','replace')
    hs=[]
    for line in text.splitlines():
        m=re.search(r'/file/([0-9a-fA-F]{32})',line)
        if m:hs.append(m.group(1).lower())
    if not hs:raise RuntimeError('no benchmark hashes parsed')
    hs=sorted(set(hs),key=lambda h:hashlib.sha256((PREFIX+h).encode()).hexdigest())
    return hs[:N]

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=45) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(data)}
    raw,codec=normalize(data);p.write_bytes(raw)
    return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'codec':codec,'sha256_cnf':hashlib.sha256(raw).hexdigest()}

def main():
    shard=int(os.environ.get('SHARD','0'));nshards=int(os.environ.get('NSHARDS','8'));root=Path('v18_scan');root.mkdir(exist_ok=True)
    chosen=benchmark_hashes();out=[]
    for rank,h in enumerate(chosen):
        if rank%nshards!=shard:continue
        p=root/(h+'.cnf');rec={'rank':rank,'hash':h,'selection_digest':hashlib.sha256((PREFIX+h).encode()).hexdigest()}
        try:
            rec.update(download(h,p))
            if rec['download']=='ok':
                t=time.perf_counter();n,clauses=parse(p);d=analyze(n,clauses);rec['topology_s']=time.perf_counter()-t
                rec.update({k:v for k,v in d.items() if k!='components_json'})
                rec['v18_route']=bool(d['largest_xor_comp_vars']>=1000 and d['gate_condensation_depth']>=4)
        except Exception as e:rec.update(download='failed',error=str(e),v18_route=False)
        p.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
