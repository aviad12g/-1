#!/usr/bin/env python3
import csv,json
from pathlib import Path
from v17_topology import download,parse,analyze
TARGETS=[
('e685a5d96e1ee9e051f191eca84b0d88','datapath-equivalence-checking','unsat'),
('12535b3264a9c88bac14522171b497ef','datapath-equivalence-checking','unsat'),
]
root=Path('v18_recheck');root.mkdir(exist_ok=True);rows=[]
for h,fam,known in TARGETS:
 p=root/(h+'.cnf');r={'hash':h,'family':fam,'known':known}
 try:
  r.update(download(h,p));n,c=parse(p);r.update(analyze(n,c))
 except Exception as e:r['error']=str(e)
 p.unlink(missing_ok=True);rows.append(r);print(json.dumps(r),flush=True)
fields=sorted({k for r in rows for k in r})
with open(root/'controls.csv','w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
