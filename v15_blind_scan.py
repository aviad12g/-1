#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,subprocess,sys,urllib.request
from pathlib import Path

PREFIX='SAT-RAG-V15|'; START=30; STOP=150; MAX_DOWNLOAD=25_000_000; MAX_DECOMPRESSED=120_000_000

def normalize(data):
    codec='plain'
    if data.startswith(b'\xfd7zXZ\x00'):codec='xz';raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):codec='gzip';raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):codec='bzip2';raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_DECOMPRESSED:raise ValueError('decompressed_too_large')
    head=raw[:1_000_000].decode('ascii','ignore')
    if not any(x.startswith('p cnf ') for x in head.splitlines()):raise ValueError('no_dimacs_header')
    return raw,codec

def download(h,path):
    try:
        with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=35) as f:data=f.read(MAX_DOWNLOAD+1)
        if len(data)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(data)}
        raw,codec=normalize(data);path.write_bytes(raw)
        return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),'codec':codec,'sha256_cnf':hashlib.sha256(raw).hexdigest()}
    except Exception as e:return {'download':'failed','error':str(e)}

def main():
    shard=int(os.environ.get('SHARD','0')); nshards=int(os.environ.get('NSHARDS','4')); root=Path('v15_scan');root.mkdir(exist_ok=True)
    urllib.request.urlretrieve('https://raw.githubusercontent.com/satcompetition/2026/main/downloads/benchmark-compilation-script/selected_benchmarks.csv',root/'selected.csv')
    with open(root/'selected.csv',newline='') as f:rows=list(csv.DictReader(f))
    seen={x.strip() for x in Path('v15_seen_hashes.txt').read_text().splitlines() if x.strip()}
    cand=[r for r in rows if r['hash'] not in seen];cand.sort(key=lambda r:hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest())
    chosen=cand[START:STOP]
    out=[]
    for global_rank,r in enumerate(chosen,start=START):
        if global_rank % nshards != shard:continue
        path=root/(r['hash']+'.cnf');rec={'global_rank':global_rank,'hash':r['hash'],'author':r['author'],'family':r['family'],'known':r['result'],'selection_digest':hashlib.sha256((PREFIX+r['hash']).encode()).hexdigest()}
        rec.update(download(r['hash'],path))
        if rec['download']=='ok':
            try:
                p=subprocess.run(['./v15_router',str(path),'--analyze-only','--budget-ms','300','--pre-ms','250'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=1.0)
                d=json.loads(p.stdout.strip().splitlines()[-1]);rec.update({k:d.get(k) for k in ['n','m','status','route','total_s','sample_s','short_frac','dup_frac','equations','other_clauses','internal_affine_vars','boundary_vars','projected_xors','internal_frac','output_ratio']})
                rec['structurally_routable']=bool(d.get('route')=='direct-affine' or ((d.get('internal_frac') or 0)>=0.65 and (d.get('output_ratio') or 1)<=0.25 and (d.get('equations') or 0)>0))
            except Exception as e:rec.update(status='scan_error',error_scan=str(e),structurally_routable=False)
            path.unlink(missing_ok=True)
        out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)

if __name__=='__main__':main()
