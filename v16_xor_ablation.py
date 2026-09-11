#!/usr/bin/env python3
import bz2,csv,gzip,json,lzma,os,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert as recover_convert,parse_cnf

TIMEOUT=10
TARGETS=['2a38c5d48846ee1c35c4c40938082a16','5ab5ac8d66c7e375037f12a536baf721','211b0708454f7901054f5f92f525972e','7cbc3ce2052ba7c5b501f75af58ab3c4']

def norm(d):
    if d.startswith(b'\xfd7zXZ\x00'):return lzma.decompress(d)
    if d.startswith(b'\x1f\x8b'):return gzip.decompress(d)
    if d.startswith(b'BZh'):return bz2.decompress(d)
    return d

def plain_convert(inp,out):
    n,clauses=parse_cnf(inp)
    with open(out,'w') as f:
        f.write(f'p xnf {n} {len(clauses)}\n')
        for c in clauses:f.write(' '.join(map(str,c))+' 0\n')

def run(binpath,path,args):
    t=time.perf_counter()
    try:p=subprocess.run([binpath,'-vb','0','-t',str(TIMEOUT),*args,str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=TIMEOUT+2)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t}
    return {'status':'SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'TIMEOUT' if p.returncode==0 else 'ERROR','wall_s':time.perf_counter()-t,'returncode':p.returncode}

def main():
    root=Path('v16_ablation');root.mkdir(exist_ok=True);xb=os.environ['XORRICANE'];meta={r['hash']:r for r in csv.DictReader(open('v15_nearmiss_candidates.csv'))};rows=[]
    for h in TARGETS:
        r=meta[h];cnf=root/(h+'.cnf');plain=root/(h+'.plain.xnf');rec=root/(h+'.recovered.xnf')
        with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:d=f.read()
        cnf.write_bytes(norm(d));plain_convert(cnf,plain);rm=recover_convert(cnf,rec)
        for mode,path,args in [('plain_default',plain,[]),('recovered_default',rec,[]),('plain_lbd',plain,['-il','-1','-delh','lbd']),('recovered_lbd',rec,['-il','-1','-delh','lbd'])]:
            res=run(xb,path,args);row={'hash':h,'family':r['family'],'known':r['known'],'variant':mode,'xors_recovered':rm.get('xors',''),**res};rows.append(row);print(json.dumps(row),flush=True)
    import csv as C
    fields=sorted({k for r in rows for k in r})
    with open(root/'results.csv','w',newline='') as f:w=C.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
if __name__=='__main__':main()
