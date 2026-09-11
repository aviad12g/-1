#!/usr/bin/env python3
import bz2,csv,gzip,hashlib,json,lzma,os,sys,urllib.request
from pathlib import Path

META_URL='https://raw.githubusercontent.com/satcompetition/2024/main/downloads/meta.csv'
MAX_DOWNLOAD=25_000_000; MAX_RAW=120_000_000
MAX_NEG_BINARY=3_000_000; MAX_POS=200_000; MAX_PAIR_CHECKS=25_000_000; MAX_K=64

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('decompressed_too_large')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:d=f.read(MAX_DOWNLOAD+1)
    if len(d)>MAX_DOWNLOAD:return {'download':'too_large','download_bytes':len(d)}
    raw=normalize(d);p.write_bytes(raw)
    return {'download':'ok','download_bytes':len(d),'cnf_bytes':len(raw),'sha256_cnf':hashlib.sha256(raw).hexdigest()}

def read_meta(path):
    rows=[]
    with open(path,encoding='utf-8',errors='replace') as f:
        hdr=f.readline().strip().split()
        if hdr[:4]!=['hash','filename','family','author']:raise ValueError('bad metadata header')
        for line in f:
            p=line.strip().split()
            if len(p)>=4:rows.append({'hash':p[0],'filename':p[1],'family':p[2],'author':p[3]})
    return rows

def pair_key(a,b):
    if a>b:a,b=b,a
    # signed literals are bounded by DIMACS int range here; stringify-free tuple is fine.
    return (a,b)

def scan(path):
    negpairs=set(); candidates=[]; n=0;m_hdr=0;m_seen=0;units=0;binary=0;longs=0;cap=False
    cur=[]
    with open(path,errors='ignore') as f:
        for line in f:
            s=line.strip()
            if not s or s.startswith('c'):continue
            if s.startswith('p '):
                q=s.split();n=int(q[2]);m_hdr=int(q[3]);continue
            if s.startswith('%'):break
            for tok in s.split():
                x=int(tok)
                if x:cur.append(x);continue
                c=tuple(cur);cur=[];m_seen+=1
                if len(c)==1:units+=1
                elif len(c)==2:
                    binary+=1
                    # Store every binary clause. For ALO literal pair li,lj, AMO requires (-li OR -lj).
                    if len(negpairs)<MAX_NEG_BINARY:negpairs.add(pair_key(c[0],c[1]))
                    else:cap=True
                else:longs+=1
                if 3<=len(c)<=MAX_K and len(set(map(abs,c)))==len(c) and len(candidates)<MAX_POS:
                    candidates.append(c)
    if cur:raise ValueError('unterminated_clause')
    pair_checks=0;groups=[];covered_pairs=set();covered_alo=0;vars_cov=set();sizes=[]
    # Longest first so large exact-one structures are measured before check budget expires.
    candidates.sort(key=len,reverse=True)
    for c in candidates:
        need=len(c)*(len(c)-1)//2
        if pair_checks+need>MAX_PAIR_CHECKS:cap=True;break
        pair_checks+=need;req=[];ok=True
        for i in range(len(c)):
            for j in range(i+1,len(c)):
                k=pair_key(-c[i],-c[j]);req.append(k)
                if k not in negpairs:ok=False;break
            if not ok:break
        if ok:
            groups.append(c);covered_alo+=1;sizes.append(len(c))
            covered_pairs.update(req);vars_cov.update(abs(x) for x in c)
    covered_unique=len(covered_pairs)+covered_alo
    compressed=(m_seen-covered_unique)+len(groups)
    return {'n':n,'m':m_seen,'m_header':m_hdr,'units':units,'binary_clauses':binary,'long_clauses':longs,
            'binary_indexed':len(negpairs),'alo_candidates':len(candidates),'pair_checks':pair_checks,'scan_capped':cap,
            'exactly_one_groups':len(groups),'eo_vars_covered':len(vars_cov),'eo_var_fraction':len(vars_cov)/max(1,n),
            'eo_pair_clauses_covered':len(covered_pairs),'eo_clauses_covered_unique':covered_unique,
            'eo_clause_fraction':covered_unique/max(1,m_seen),'eo_compressed_constraints':compressed,
            'eo_compression_ratio':compressed/max(1,m_seen),'eo_max_arity':max(sizes) if sizes else 0,
            'eo_median_arity':sorted(sizes)[len(sizes)//2] if sizes else 0}

def main():
    shard=int(os.environ.get('SHARD','0'));nshards=int(os.environ.get('NSHARDS','8'))
    root=Path('v22_cardinality_scan');root.mkdir(exist_ok=True)
    meta=root/'meta.csv';urllib.request.urlretrieve(META_URL,meta);rows=read_meta(meta);out=[]
    for rank,r in enumerate(rows):
        if rank%nshards!=shard:continue
        rec={'year':2024,'meta_rank':rank,**r};p=root/(r['hash']+'.cnf')
        try:
            rec.update(download(r['hash'],p))
            if rec['download']=='ok':rec.update(scan(p))
        except Exception as e:rec.update(download='failed',error=type(e).__name__+': '+str(e))
        finally:p.unlink(missing_ok=True)
        out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/f'scan_{shard}.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    summary={'shard':shard,'rows':len(out),'ok':sum(r.get('download')=='ok' for r in out),
             'with_eo':sum((r.get('exactly_one_groups') or 0)>0 for r in out),
             'strong_eo':sum((r.get('eo_clause_fraction') or 0)>=0.20 for r in out),
             'failed':sum(r.get('download')=='failed' for r in out),'too_large':sum(r.get('download')=='too_large' for r in out)}
    (root/f'summary_{shard}.json').write_text(json.dumps(summary,indent=2));print('SUMMARY',json.dumps(summary),flush=True)
if __name__=='__main__':main()
