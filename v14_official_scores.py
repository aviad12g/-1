#!/usr/bin/env python3
import csv, sys, urllib.request
from pathlib import Path

BASE='https://raw.githubusercontent.com/satcompetition/2026/main/downloads/'
files={
 'scores.csv': BASE+'scores.csv',
 'selected_benchmarks.csv': BASE+'benchmark-compilation-script/selected_benchmarks.csv',
 'benchmarks2026.csv': BASE+'benchmark-compilation-script/benchmarks2026.csv',
}
for fn,url in files.items():
    print('DOWNLOAD',url,flush=True)
    urllib.request.urlretrieve(url,fn)

# Print schema/header and a few rows exactly, so future parsing is auditable.
for fn in ['scores.csv','selected_benchmarks.csv']:
    print('\nFILE',fn)
    with open(fn,encoding='utf-8',errors='replace') as f:
        for i,line in zip(range(6),f):
            print('HEAD',i,repr(line.rstrip('\n')))

needles=[
 '01d6fa8efd18ebfecd06af408958477b',
 'c4904e76974e686d',
 'lightsout_sat_25_unbounded_direct_planted250_4_sat',
 '75429ff7acb5acb597abe01aa745c2a6',
 'e084fb10de0558a8',
 'tseitin-formulas',
]

text=Path('scores.csv').read_text(encoding='utf-8',errors='replace').splitlines()
for needle in needles:
    hits=[line for line in text if needle.lower() in line.lower()]
    print('\nNEEDLE',needle,'HITS',len(hits))
    for line in hits[:80]: print('HIT',line)

# Also inspect CSV dialect and columns safely.
with open('scores.csv',newline='',encoding='utf-8',errors='replace') as f:
    sample=f.read(32768); f.seek(0)
    try: dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
    except Exception: dialect=csv.excel
    reader=csv.reader(f,dialect)
    rows=[]
    for i,row in zip(range(5),reader): rows.append(row)
    print('\nDIALECT',repr(dialect.delimiter))
    for i,row in enumerate(rows): print('ROW',i,row)

# Generic extraction: retain any score row mentioning known ids OR a likely benchmark index
# after resolving selected_benchmarks.csv. This avoids assuming the score schema.
sel_lines=Path('selected_benchmarks.csv').read_text(encoding='utf-8',errors='replace').splitlines()
selected=[]
for line in sel_lines:
    if any(n.lower() in line.lower() for n in needles[:5]): selected.append(line)
Path('v14_selected_metadata.txt').write_text('\n'.join(selected)+'\n')

# Produce a compact audit file for artifact download.
out=[]
out.append('SCORES HEADER / SAMPLE')
out.extend(text[:5])
for needle in needles:
    hits=[line for line in text if needle.lower() in line.lower()]
    out.append(f'\n## {needle} ({len(hits)} direct hits)')
    out.extend(hits[:200])
Path('v14_official_score_audit.txt').write_text('\n'.join(out)+'\n')
print('\nDONE')
