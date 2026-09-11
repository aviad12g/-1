#!/usr/bin/env python3
import bz2,csv,gzip,json,lzma,os,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert
TIMEOUT=10

def norm(d):
    if d.startswith(b'\xfd7zXZ\x00'):return lzma.decompress(d)
    if d.startswith(b'\x1f\x8b'):return gzip.decompress(d)
    if d.startswith(b'BZh'):return bz2.decompress(d)
    return d

def main():
    root=Path('v16_avgutil');root.mkdir(exist_ok=True);xb=os.environ['XORRICANE'];out=[]
    for r in csv.DictReader(open('v15_nearmiss_candidates.csv')):
        h=r['hash'];cnf=root/(h+'.cnf');xnf=root/(h+'.xnf')
        with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:cnf.write_bytes(norm(f.read()))
        t=time.perf_counter();meta=convert(cnf,xnf);conv=time.perf_counter()-t
        t=time.perf_counter()
        try:p=subprocess.run([xb,'-vb','0','-t','10','-il','-1',str(xnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=12);wall=time.perf_counter()-t;st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'TIMEOUT' if p.returncode==0 else 'ERROR'
        except subprocess.TimeoutExpired:wall=time.perf_counter()-t;st='TIMEOUT'
        row={'hash':h,'family':r['family'],'known':r['known'],'xors':meta.get('xors'),'conversion_s':conv,'solver_s':wall,'total_s':conv+wall,'status':st};out.append(row);print(json.dumps(row),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'results.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
