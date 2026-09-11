#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,sys,urllib.request
from pathlib import Path
from v17_topology import parse, analyze
from v19_router import route, RULE_TEXT

META_URL='https://raw.githubusercontent.com/satcompetition/2024/main/downloads/meta.csv'
MAX_DOWNLOAD=25_000_000
MAX_RAW=120_000_000
sys.setrecursionlimit(1_000_000)

# V20 uses the entire SAT Competition 2024 meta list as a new-year validation
# universe.  The V19 router is imported unchanged.  No solver is invoked here.

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'): raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'): raw=gzip.decompress(data)
    elif data.startswith(b'BZh'): raw=bz2.decompress(data)
    else: raw=data
    if len(raw)>MAX_RAW: raise ValueError('decompressed_too_large')
    head=raw[:1_000_000].decode('ascii','ignore')
    if not any(line.startswith('p cnf ') for line in head.splitlines()):
        raise ValueError('no_dimacs_header')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:
        data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:
        return {'download':'too_large','download_bytes':len(data)}
    raw=normalize(data); p.write_bytes(raw)
    return {'download':'ok','download_bytes':len(data),'cnf_bytes':len(raw),
            'sha256_cnf':hashlib.sha256(raw).hexdigest()}

def read_meta(path):
    rows=[]
    with open(path,encoding='utf-8',errors='replace') as f:
        header=f.readline().strip().split()
        if header[:4] != ['hash','filename','family','author']:
            raise ValueError('unexpected 2024 meta header: '+repr(header))
        for line in f:
            p=line.strip().split()
            if len(p)<4: continue
            rows.append({'hash':p[0],'filename':p[1],'family':p[2],'author':p[3]})
    return rows

def exclusions():
    s=set()
    p=Path('v15_seen_hashes.txt')
    if p.exists(): s.update(x.strip() for x in p.read_text().splitlines() if x.strip())
    # Explicitly exclude every routed hash already used in V17/V18/V19 if present.
    for name in ['v17_frozen_candidates.csv','v18_frozen_candidates.csv','v19_frozen_candidates.csv']:
        p=Path(name)
        if p.exists():
            try:
                for r in csv.DictReader(open(p)): s.add(r['hash'])
            except Exception: pass
    return s

def main():
    shard=int(os.environ.get('SHARD','0')); nshards=int(os.environ.get('NSHARDS','16'))
    root=Path('v20_scan');root.mkdir(exist_ok=True)
    meta=root/'meta.csv'; urllib.request.urlretrieve(META_URL,meta)
    rows=read_meta(meta); excluded=exclusions()
    out=[]
    for rank,r in enumerate(rows):
        if rank % nshards != shard: continue
        h=r['hash']; rec={'year':2024,'meta_rank':rank,**r,'prior_excluded':h in excluded,
                          'v19_rule':RULE_TEXT}
        if h in excluded:
            rec.update(download='excluded',v19_route=False); out.append(rec); print(json.dumps(rec),flush=True); continue
        p=root/(h+'.cnf')
        try:
            rec.update(download(h,p))
            if rec['download']=='ok':
                n,clauses=parse(p); d=analyze(n,clauses); selected,diag=route(d)
                rec.update({k:v for k,v in d.items() if k!='components_json'})
                rec.update(diag); rec['v19_route']=bool(selected)
        except Exception as e:
            rec.update(download='failed',error=type(e).__name__+': '+str(e),v19_route=False)
        finally:
            p.unlink(missing_ok=True)
        out.append(rec); print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    summary={'shard':shard,'rows':len(out),'download_ok':sum(r.get('download')=='ok' for r in out),
             'routed':sum(bool(r.get('v19_route')) for r in out),'failed':sum(r.get('download')=='failed' for r in out),
             'too_large':sum(r.get('download')=='too_large' for r in out),'excluded':sum(r.get('download')=='excluded' for r in out)}
    (root/f'summary_{shard}.json').write_text(json.dumps(summary,indent=2)); print('SUMMARY',json.dumps(summary),flush=True)
if __name__=='__main__': main()
