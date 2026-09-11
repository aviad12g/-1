#!/usr/bin/env python3
"""Frozen SAT-RAG V18 topology-quality router.

The score was derived only from pre-V18 development cases (V16/V17 outcomes).
It is intentionally family-name agnostic and uses only exact structural features.
"""
import math

LOW_SEMANTIC_CUTOFF = 0.26
HIGH_SEMANTIC_CUTOFF = 0.63
SEMANTIC_SPLIT = 0.90
MIN_COMPONENT_VARS = 1000
MIN_DAG_DEPTH = 4


def score(d):
    """Return (Q, diagnostics) from one v17_topology.analyze record."""
    comp_vars = float(d.get('largest_xor_comp_vars', 0) or 0)
    xor_vars = float(d.get('xor_vars', 0) or 0)
    rank = float(d.get('largest_xor_comp_rank', 0) or 0)
    boundary_rank = float(d.get('largest_xor_comp_boundary_rank', 0) or 0)
    depth = float(d.get('gate_condensation_depth', 0) or 0)
    dag_edges = float(d.get('gate_condensation_edges', 0) or 0)
    cyclic_focus = float(d.get('gate_largest_scc_frac', 0) or 0)
    residual_locality = float(d.get('residual_one_module_frac', 0) or 0)

    coherence = comp_vars / max(1.0, xor_vars)
    rank_gain = rank / max(1.0, boundary_rank + 1.0)
    dag_width_proxy = (dag_edges + 1.0) / (depth + 1.0)

    # Core term: a coherent affine backbone with useful rank, concentrated nonlinear
    # feedback, and a deep-but-not-broad condensation DAG.
    core = (coherence * rank_gain * cyclic_focus * math.log(depth + 2.0) /
            (1.0 + math.log1p(dag_width_proxy)))

    # Locality bonus: residual clauses that stay inside one semantic module are
    # cheaper than clauses coupling several modules.
    locality = coherence * rank_gain * cyclic_focus * residual_locality
    q = core + locality
    return q, {
        'v18_coherence': coherence,
        'v18_rank_gain': rank_gain,
        'v18_dag_width_proxy': dag_width_proxy,
        'v18_core': core,
        'v18_locality_bonus': locality,
    }


def route(d):
    q, diag = score(d)
    semantic = float(d.get('semantic_fraction', 0) or 0)
    depth = float(d.get('gate_condensation_depth', 0) or 0)
    comp_vars = float(d.get('largest_xor_comp_vars', 0) or 0)
    cutoff = HIGH_SEMANTIC_CUTOFF if semantic >= SEMANTIC_SPLIT else LOW_SEMANTIC_CUTOFF
    selected = bool(comp_vars >= MIN_COMPONENT_VARS and depth >= MIN_DAG_DEPTH and q >= cutoff)
    diag.update({
        'v18_score': q,
        'v18_cutoff': cutoff,
        'v18_route': selected,
        'v18_semantic_regime': 'high' if semantic >= SEMANTIC_SPLIT else 'mixed',
    })
    return selected, diag


RULE_TEXT = (
    'largest_xor_comp_vars>=1000 && gate_condensation_depth>=4 && '
    'Q>=0.63 if semantic_fraction>=0.90 else Q>=0.26; '
    'Q=coherence*rank_gain*SCCfocus*log(depth+2)/(1+log1p(width)) '
    '+ coherence*rank_gain*SCCfocus*residual_one_module_frac'
)
