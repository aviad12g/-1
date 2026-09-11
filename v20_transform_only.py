#!/usr/bin/env python3
import hashlib,json,time,urllib.request
from pathlib import Path
from v16_cnf_to_xnf import convert
from v20_certify_v19 import HASH,norm,independent_transform_check

root=Path('v20_transform_only');root.mkdir(exist_ok=True)
cnf=root/(HASH+'.cnf');xnf=root/(HASH+'.xnf')
with urllib.request.urlopen('https://benchmark-database.de/file/'+HASH,timeout=40) as f:raw=norm(f.read())
cnf.write_bytes(raw)
t=time.perf_counter();meta=convert(cnf,xnf);conv=time.perf_counter()-t
cert=independent_transform_check(cnf,xnf)
cert.update(hash=HASH,cnf_sha256=hashlib.sha256(raw).hexdigest(),convert_s=conv,converter_meta=meta)
(root/'transform_certificate.json').write_text(json.dumps(cert,indent=2))
print(json.dumps({k:v for k,v in cert.items() if k!='equation_checks'},indent=2))
