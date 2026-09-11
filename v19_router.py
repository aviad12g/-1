#!/usr/bin/env python3
"""Frozen SAT-RAG V19 router.

V19 was derived after the clean V18 false positive exposed a missing absolute
interface-size cost. It preserves V18's exact topology score and adds one
engineering-motivated boundary penalty. No benchmark-family names are used.
"""
from v18_router import score as v18_score

BOUNDARY_SCALE = 2048.0
LOW_SEMANTIC_CUTOFF = 0.19
HIGH_SEMANTIC_CUTOFF = 0.40
SEMANTIC_SPLIT = 0.90
MIN_COMPONENT_VARS = 1000
MIN_DAG_DEPTH = 4


def score(d):
    q18, diag = v18_score(d)
    boundary = float(d.get('largest_xor_comp_boundary', 0) or 0)
    penalty = 1.0 + boundary / BOUNDARY_SCALE
    q19 = q18 / penalty
    diag.update({
        'v19_q18': q18,
        'v19_boundary': boundary,
        'v19_boundary_penalty': penalty,
        'v19_score': q19,
    })
    return q19, diag


def route(d):
    q, diag = score(d)
    semantic = float(d.get('semantic_fraction', 0) or 0)
    depth = float(d.get('gate_condensation_depth', 0) or 0)
    comp_vars = float(d.get('largest_xor_comp_vars', 0) or 0)
    cutoff = HIGH_SEMANTIC_CUTOFF if semantic >= SEMANTIC_SPLIT else LOW_SEMANTIC_CUTOFF
    selected = bool(comp_vars >= MIN_COMPONENT_VARS and depth >= MIN_DAG_DEPTH and q >= cutoff)
    diag.update({
        'v19_cutoff': cutoff,
        'v19_route': selected,
        'v19_semantic_regime': 'high' if semantic >= SEMANTIC_SPLIT else 'mixed',
    })
    return selected, diag

RULE_TEXT = (
    'largest_xor_comp_vars>=1000 && gate_condensation_depth>=4 && '
    'Q19>=0.40 if semantic_fraction>=0.90 else Q19>=0.19; '
    'Q19=Q18/(1+largest_xor_comp_boundary/2048)'
)
