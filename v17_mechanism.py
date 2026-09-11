#!/usr/bin/env python3
import bz2,csv,gzip,json,lzma,os,re,subprocess,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert

MAX_DOWNLOAD=35_000_000;MAX_RAW=180_000_000

def normalize(data):
    if data.startswith(b'\xfd7zXZ\x00'):raw=lzma.decompress(data)
    elif data.startswith(b'\x1f\x8b'):raw=gzip.decompress(data)
    elif data.startswith(b'BZh'):raw=bz2.decompress(data)
    else:raw=data
    if len(raw)>MAX_RAW:raise ValueError('too_large_raw')
    return raw

def download(h,p):
    with urllib.request.urlopen('https://benchmark-database.de/file/'+h,timeout=40) as f:data=f.read(MAX_DOWNLOAD+1)
    if len(data)>MAX_DOWNLOAD:raise ValueError('too_large_download')
    raw=normalize(data);p.write_bytes(raw);return len(raw)

def parse_stat(text,label):
    m=re.search(r'^c\s+'+re.escape(label)+r'\s*:\s*([0-9]+)',text,re.M)
    return int(m.group(1)) if m else None

def parse_float(text,label):
    m=re.search(r'^c\s+'+re.escape(label)+r'\s*:\s*([0-9.]+)',text,re.M)
    return float(m.group(1)) if m else None

def run(xorricane,xnf,timeout=5):
    t=time.perf_counter()
    p=subprocess.run([xorricane,'-vb','1','-t',str(timeout),'-il','-1','-delh','lbd',str(xnf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=timeout+3)
    wall=time.perf_counter()-t;txt=p.stdout
    status='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'TIMEOUT' if p.returncode==0 else 'ERROR'
    d={'status':status,'wall_s':wall,'returncode':p.returncode}
    for lbl,key in [('decisions','decisions'),('conflicts','conflicts'),('restarts','restarts'),('CGP props','cgp_props'),('LGJ props','lgj_props'),('GE calls','ge_calls'),('GE props','ge_props'),('IG calls','ig_calls'),('IG props','ig_props')]:d[key]=parse_stat(txt,lbl)
    d['reported_total_s']=parse_float(txt,'Total time')
    dec=d.get('decisions') or 0
    d['lgj_per_decision']=(d.get('lgj_props') or 0)/max(1,dec);d['ge_per_decision']=(d.get('ge_props') or 0)/max(1,dec);d['ig_per_decision']=(d.get('ig_props') or 0)/max(1,dec);d['cgp_per_decision']=(d.get('cgp_props') or 0)/max(1,dec)
    return d

def main():
    root=Path('v17_mechanism');root.mkdir(exist_ok=True);xorricane=os.environ['XORRICANE'];rows=list(csv.DictReader(open('v15_nearmiss_candidates.csv')));out=[]
    for r in rows:
        cnf=root/(r['hash']+'.cnf');xnf=root/(r['hash']+'.xnf');rec=dict(r)
        try:
            rec['cnf_bytes']=download(r['hash'],cnf);meta=convert(cnf,xnf);rec.update({'xors':meta['xors'],'xnf_clauses':meta['xnf_clauses'],'compression_ratio':meta['compression_ratio']});rec.update(run(xorricane,xnf))
        except Exception as e:rec['error']=str(e)
        cnf.unlink(missing_ok=True);xnf.unlink(missing_ok=True);out.append(rec);print(json.dumps(rec),flush=True)
    fields=sorted({k for r in out for k in r})
    with open(root/'mechanism.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
if __name__=='__main__':main()
