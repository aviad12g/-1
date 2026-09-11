#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from v16_cnf_to_xnf import parse_cnf,recover,is_encoding_clause

def convert(inp,out):
    n,clauses=parse_cnf(inp);rec,order,contradiction=recover(clauses)
    if contradiction:
        with open(out,'w') as f:f.write('p cnf 1 2\n1 0\n-1 0\n')
        return {'status':'UNSAT','n':n,'m':len(clauses),'xors':len(order)}
    kept=[c for c in clauses if not is_encoding_clause(c,rec)]
    with open(out,'w') as f:
        f.write(f'p cnf {n} {len(kept)+len(order)}\n')
        for c in kept:f.write(' '.join(map(str,c))+' 0\n')
        for key in order:
            forbidden,rhs=rec[key];lits=list(key)
            # CryptoMiniSat x-line means XOR of listed literals = true.
            if rhs==0:lits[0]=-lits[0]
            f.write('x'+' '.join(map(str,lits))+' 0\n')
    return {'status':'OK','n':n,'m':len(clauses),'xors':len(order),'kept':len(kept),'out_constraints':len(kept)+len(order),'compression_ratio':(len(kept)+len(order))/max(1,len(clauses))}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('output');a=ap.parse_args();print(json.dumps(convert(a.input,a.output)))
if __name__=='__main__':main()
