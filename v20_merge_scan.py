#!/usr/bin/env python3
import csv,json,glob
from pathlib import Path

files=sorted(glob.glob('v20_parts/**/scan_*.csv',recursive=True))
if not files: raise SystemExit('no shard CSVs found')
rows=[]
for fn in files:
    rows.extend(csv.DictReader(open(fn,encoding='utf-8',errors='replace')))
# Deduplicate defensively by (year,hash); matrix shards should already be disjoint.
uniq={}
for r in rows: uniq[(r.get('year','2024'),r['hash'])]=r
rows=list(uniq.values());rows.sort(key=lambda r:int(r.get('meta_rank',0)))
routed=[r for r in rows if str(r.get('v19_route','')).lower() in ('true','1','yes')]
root=Path('v20_merged');root.mkdir(exist_ok=True)
fields=sorted({k for r in rows for k in r})
with open(root/'v20_2024_scan.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
rf=sorted({k for r in routed for k in r}) if routed else ['hash']
with open(root/'v20_frozen_candidates.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rf);w.writeheader();w.writerows(routed)
summary={
 'rows_total':len(rows),
 'download_ok':sum(r.get('download')=='ok' for r in rows),
 'routed':len(routed),
 'failed':sum(r.get('download')=='failed' for r in rows),
 'too_large':sum(r.get('download')=='too_large' for r in rows),
 'excluded':sum(r.get('download')=='excluded' for r in rows),
 'families_routed':{},
 'routed_hashes':[r['hash'] for r in routed],
}
for r in routed: summary['families_routed'][r.get('family','')]=summary['families_routed'].get(r.get('family',''),0)+1
(root/'v20_scan_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True))
print(json.dumps(summary,indent=2,sort_keys=True))
