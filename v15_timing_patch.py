#!/usr/bin/env python3
from pathlib import Path

# Mechanical instrumentation only. This does not alter the frozen selection,
# structural thresholds, solver options, or routing decisions.
p=Path('v15_router.cpp')
s=p.read_text()
s=s.replace('bool model_ok=false;double solver_s=0;', 'bool model_ok=false;double solver_s=0,verify_s=0;')
s=s.replace('auto model=backsolve_full(h.n,br.piv);model_ok=verify_model(input,model);status=model_ok?"SAT":"ERROR";', 'auto model=backsolve_full(h.n,br.piv);auto vt=Clock::now();model_ok=verify_model(input,model);verify_s+=sec_since(vt);status=model_ok?"SAT":"ERROR";')
s=s.replace('auto cm=parse_model(rr.out,h.n);auto model=reconstruct(h.n,cl,pr,cm);model_ok=verify_model(input,model);status=model_ok?"SAT":"ERROR";', 'auto cm=parse_model(rr.out,h.n);auto model=reconstruct(h.n,cl,pr,cm);auto vt=Clock::now();model_ok=verify_model(input,model);verify_s+=sec_since(vt);status=model_ok?"SAT":"ERROR";')
s=s.replace('auto m=parse_model(rr.out,h.n);model_ok=verify_model(input,m);if(!model_ok)status="ERROR";', 'auto m=parse_model(rr.out,h.n);auto vt=Clock::now();model_ok=verify_model(input,m);verify_s+=sec_since(vt);if(!model_ok)status="ERROR";')
s=s.replace('std::cout<<",\\"total_s\\":"<<total<<",\\"solver_s\\":"<<solver_s', 'std::cout<<",\\"total_s\\":"<<total<<",\\"algorithm_s\\":"<<(total-verify_s)<<",\\"verify_s\\":"<<verify_s<<",\\"solver_s\\":"<<solver_s')
p.write_text(s)

p=Path('v15_benchmark.py')
s=p.read_text()
old="""def run(cmd,timeout,path=None):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:return {'status':'TIMEOUT','wall_s':time.perf_counter()-t,'model_ok':''}
    wall=time.perf_counter()-t
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'ERROR'
    ok=''
    if st=='SAT' and path is not None:ok=verify_model(path,parse_model(p.stdout))
    return {'status':st,'wall_s':wall,'model_ok':ok}
"""
new="""def run(cmd,timeout,path=None):
    t=time.perf_counter()
    try:p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired:
        wall=time.perf_counter()-t
        return {'status':'TIMEOUT','wall_s':wall,'total_s':wall,'verify_s':0.0,'model_ok':''}
    st='SAT' if p.returncode==10 else 'UNSAT' if p.returncode==20 else 'ERROR'
    ok=''; verify_s=0.0
    if st=='SAT' and path is not None:
        model=parse_model(p.stdout)
        algorithm_s=time.perf_counter()-t
        vt=time.perf_counter();ok=verify_model(path,model);verify_s=time.perf_counter()-vt
    else:
        algorithm_s=time.perf_counter()-t
    total_s=time.perf_counter()-t
    return {'status':st,'wall_s':algorithm_s,'total_s':total_s,'verify_s':verify_s,'model_ok':ok}
"""
if old not in s: raise SystemExit('run block not found')
s=s.replace(old,new,1)
old="""    wall=time.perf_counter()-t
    try:d=json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:return {'status':'ERROR','wall_s':wall,'route':'parse-error','model_ok':'','raw':p.stdout[-1000:]}
    return {'status':d.get('status'),'wall_s':wall,'route':d.get('route'),'model_ok':d.get('model_ok',''),
            'sample_s':d.get('sample_s'),'short_frac':d.get('short_frac'),'dup_frac':d.get('dup_frac'),
            'equations':d.get('equations'),'internal_frac':d.get('internal_frac'),'output_ratio':d.get('output_ratio')}
"""
new="""    total_s=time.perf_counter()-t
    try:d=json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:return {'status':'ERROR','wall_s':total_s,'total_s':total_s,'verify_s':0.0,'route':'parse-error','model_ok':'','raw':p.stdout[-1000:]}
    verify_s=float(d.get('verify_s',0.0) or 0.0)
    algorithm_s=max(0.0,total_s-verify_s)
    return {'status':d.get('status'),'wall_s':algorithm_s,'total_s':total_s,'verify_s':verify_s,
            'route':d.get('route'),'model_ok':d.get('model_ok',''),
            'sample_s':d.get('sample_s'),'short_frac':d.get('short_frac'),'dup_frac':d.get('dup_frac'),
            'equations':d.get('equations'),'internal_frac':d.get('internal_frac'),'output_ratio':d.get('output_ratio')}
"""
if old not in s: raise SystemExit('v15 timing block not found')
s=s.replace(old,new,1)
p.write_text(s)
print('timing instrumentation applied')
