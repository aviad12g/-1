#!/usr/bin/env python3
import bz2,gzip,lzma,sys,urllib.request,json
from pathlib import Path
sys.setrecursionlimit(1_000_000)
from v17_topology import parse, analyze
HASHES=['04d0ae28e10d4a35ebab62f42f0200e8','cc436db9fe0278663ce376e068069815']
MAX_DOWNLOAD=25_000_000;MAX_RAW=120_000_000

def norm(data):
    if data.startswith(b'\xfd7zXZ\x00'):r=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):r=gzip.decompress(data)
    elif data.startswith(b'BZh'):r=bz2.decompress(data)
    else:r=data
    if len(r)>MAX_RAW:raise ValueError('decompressed_too_large')
    return r

out=[]
for h in HASHES:
    p=Path(h+'.cnf')
    try:
        with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(MAX_DOWNLOAD+1)
        if len(data)>MAX_DOWNLOAD:raise ValueError('download_too_large')
        raw=norm(data);p.write_bytes(raw);n,c=parse(p);d=analyze(n,c);d={k:v for k,v in d.items() if k!='components_json'};d.update(hash=h,download='ok',v17_route=bool(d['largest_xor_comp_vars']>=1000 and d['gate_condensation_depth']>=4))
    except Exception as e:d={'hash':h,'download':'failed','error':str(e),'v17_route':False}
    p.unlink(missing_ok=True);out.append(d);print(json.dumps(d),flush=True)
Path('v17_stack_recheck.json').write_text(json.dumps(out,indent=2))
