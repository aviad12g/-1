#!/usr/bin/env python3
from pathlib import Path

root = Path('kissat-rel-4.0.4/src')

# 1) Add compact snapshots of recent exact learned clauses to solver state.
p = root / 'internal.h'
s = p.read_text()
anchor = '  reference last_learned[4];\n'
insert = '''  reference last_learned[4];\n\n  /* SAT-RAG V12 experimental exact conflict memory.  This state is purely\n     heuristic: it never adds/removes clauses or changes satisfiability. */\n  int v12_mode;\n  unsigned v12_feedback_vars;\n  unsigned v12_capacity;\n  unsigned v12_max_size;\n  unsigned v12_max_glue;\n  unsigned v12_next;\n  unsigned v12_count;\n  unsigned *v12_clause_lits;\n  unsigned char *v12_clause_sizes;\n  unsigned char *v12_clause_glues;\n  uint64_t *v12_clause_epochs;\n  uint64_t v12_seen_conflicts;\n  uint64_t v12_stored_clauses;\n  uint64_t v12_stored_literals;\n  uint64_t v12_retrievals;\n  uint64_t v12_hint_uses;\n  uint64_t v12_random_uses;\n  uint64_t v12_memory_resets;\n'''
if anchor not in s: raise SystemExit('internal.h anchor missing')
s = s.replace(anchor, insert, 1)
p.write_text(s)

# 2) Expose recorder to conflict learning.
p = root / 'decide.h'
s = p.read_text()
anchor = 'int kissat_decide_phase (struct kissat *, unsigned idx);\n'
insert = anchor + 'void kissat_v12_record_learned_clause (struct kissat *, unsigned glue);\n'
if anchor not in s: raise SystemExit('decide.h anchor missing')
s = s.replace(anchor, insert, 1)
p.write_text(s)

# 3) Implement conflict snapshot storage + context-sensitive retrieval in decide.c.
p = root / 'decide.c'
s = p.read_text()
s = s.replace('#include <inttypes.h>\n', '#include <inttypes.h>\n#include <math.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n', 1)
anchor = 'static unsigned last_enqueued_unassigned_variable (kissat *solver) {'
code = r'''
/* V12 modes: 1=off, 2=exact-conflict vote, 3=matched random-sign control. */
static void v12_init_config (kissat *solver) {
  if (solver->v12_mode)
    return;
  const char *mode = getenv ("KISSAT_V12_MODE");
  if (mode && !strcmp (mode, "conflict"))
    solver->v12_mode = 2;
  else if (mode && !strcmp (mode, "random"))
    solver->v12_mode = 3;
  else
    solver->v12_mode = 1;

  solver->v12_capacity = 256;
  solver->v12_max_size = 12;
  solver->v12_max_glue = 6;
  const char *tmp;
  if ((tmp = getenv ("KISSAT_V12_CAP")) && atoi (tmp) > 0)
    solver->v12_capacity = (unsigned) atoi (tmp);
  if ((tmp = getenv ("KISSAT_V12_MAX_SIZE")) && atoi (tmp) >= 2)
    solver->v12_max_size = (unsigned) atoi (tmp);
  if ((tmp = getenv ("KISSAT_V12_MAX_GLUE")) && atoi (tmp) >= 1)
    solver->v12_max_glue = (unsigned) atoi (tmp);
}

static void v12_clear_memory (kissat *solver) {
  free (solver->v12_clause_lits);
  free (solver->v12_clause_sizes);
  free (solver->v12_clause_glues);
  free (solver->v12_clause_epochs);
  solver->v12_clause_lits = 0;
  solver->v12_clause_sizes = 0;
  solver->v12_clause_glues = 0;
  solver->v12_clause_epochs = 0;
  solver->v12_feedback_vars = 0;
  solver->v12_next = solver->v12_count = 0;
}

static bool v12_ensure_memory (kissat *solver) {
  v12_init_config (solver);
  if (solver->v12_mode == 1 || !VARS)
    return false;
  if (solver->v12_clause_lits && solver->v12_feedback_vars == VARS)
    return true;
  if (solver->v12_clause_lits) {
    v12_clear_memory (solver);
    solver->v12_memory_resets++;
  }
  const size_t cap = solver->v12_capacity;
  const size_t width = solver->v12_max_size;
  solver->v12_clause_lits = calloc (cap * width, sizeof (unsigned));
  solver->v12_clause_sizes = calloc (cap, sizeof (unsigned char));
  solver->v12_clause_glues = calloc (cap, sizeof (unsigned char));
  solver->v12_clause_epochs = calloc (cap, sizeof (uint64_t));
  if (!solver->v12_clause_lits || !solver->v12_clause_sizes ||
      !solver->v12_clause_glues || !solver->v12_clause_epochs) {
    v12_clear_memory (solver);
    return false;
  }
  solver->v12_feedback_vars = VARS;
  return true;
}

void kissat_v12_record_learned_clause (kissat *solver, unsigned glue) {
  v12_init_config (solver);
  if (solver->v12_mode == 1)
    return;
  solver->v12_seen_conflicts++;
  const unsigned size = SIZE_STACK (solver->clause);
  if (size < 2 || size > solver->v12_max_size || glue > solver->v12_max_glue)
    return;
  if (!v12_ensure_memory (solver))
    return;

  const unsigned slot = solver->v12_next;
  unsigned *dst = solver->v12_clause_lits +
                  (size_t) slot * solver->v12_max_size;
  unsigned pos = 0;
  for (all_stack (unsigned, lit, solver->clause))
    dst[pos++] = lit;
  solver->v12_clause_sizes[slot] = (unsigned char) size;
  solver->v12_clause_glues[slot] =
      (unsigned char) (glue > 255 ? 255 : glue);
  solver->v12_clause_epochs[slot] = solver->v12_seen_conflicts;
  solver->v12_next = (slot + 1) % solver->v12_capacity;
  if (solver->v12_count < solver->v12_capacity)
    solver->v12_count++;
  solver->v12_stored_clauses++;
  solver->v12_stored_literals += size;
}

static unsigned v12_hash32 (unsigned x) {
  x ^= x >> 16;
  x *= 0x7feb352du;
  x ^= x >> 15;
  x *= 0x846ca68bu;
  x ^= x >> 16;
  return x;
}

static int v12_retrieve_phase (kissat *solver, unsigned idx) {
  v12_init_config (solver);
  if (solver->v12_mode == 1 || !solver->v12_count ||
      solver->v12_feedback_vars != VARS)
    return 0;

  double score = 0.0, mass = 0.0;
  unsigned matched = 0;
  const uint64_t now = solver->v12_seen_conflicts;
  const value *values = solver->values;

  for (unsigned slot = 0; slot < solver->v12_capacity; slot++) {
    const unsigned size = solver->v12_clause_sizes[slot];
    if (!size)
      continue;
    const unsigned *lits = solver->v12_clause_lits +
                           (size_t) slot * solver->v12_max_size;
    unsigned self = INVALID_LIT, open = 0;
    bool satisfied_elsewhere = false;
    for (unsigned j = 0; j < size; j++) {
      const unsigned lit = lits[j];
      if (IDX (lit) == idx) {
        self = lit;
        continue;
      }
      const value val = values[lit];
      if (val > 0) {
        satisfied_elsewhere = true;
        break;
      }
      if (!val)
        open++;
    }
    if (self == INVALID_LIT || satisfied_elsewhere)
      continue;

    /* Prefer low-glue, currently constrained and recent learned clauses. */
    const unsigned glue = solver->v12_clause_glues[slot];
    const uint64_t age = now - solver->v12_clause_epochs[slot];
    const double recency = 1.0 / (1.0 + (double) age / 64.0);
    const double context = 1.0 / (1.0 + (double) open);
    const double weight = recency * context * context / (1.0 + glue);
    const int phase = NEGATED (self) ? -1 : 1;
    score += phase * weight;
    mass += weight;
    matched++;
  }

  solver->v12_retrievals++;
  if (matched < 2 || mass <= 0.0)
    return 0;
  const double confidence = fabs (score) / mass;
  double threshold = 0.70;
  const char *tmp = getenv ("KISSAT_V12_CONF");
  if (tmp && *tmp)
    threshold = atof (tmp);
  if (confidence < threshold)
    return 0;

  if (solver->v12_mode == 3) {
    solver->v12_random_uses++;
    /* Do not consume Kissat's RNG.  Same intervention mask, randomized sign. */
    const unsigned h = v12_hash32 (idx ^ (unsigned) now ^ 0x12a5b7c9u);
    return (h & 1u) ? 1 : -1;
  }
  solver->v12_hint_uses++;
  return score >= 0.0 ? 1 : -1;
}

'''
if anchor not in s: raise SystemExit('decide.c anchor missing')
s = s.replace(anchor, code + anchor, 1)
# Insert V12 after target and before saved phase. It can override phase-saving, not target.
anchor2 = '''  if (!res && saved && (res = *saved)) {\n    LOG ("%s uses saved decision phase %d", LOGVAR (idx), (int) res);\n    INC (saved_decisions);\n  }'''
replacement2 = '''  if (!res) {\n    const int v12 = v12_retrieve_phase (solver, idx);\n    if (v12)\n      res = v12;\n  }\n\n''' + anchor2
if anchor2 not in s: raise SystemExit('decide phase anchor missing')
s = s.replace(anchor2, replacement2, 1)
p.write_text(s)

# 4) Snapshot the exact 1-UIP learned clause before Kissat mutates/backtracks it.
p = root / 'learn.c'
s = p.read_text()
s = s.replace('#include "learn.h"\n', '#include "learn.h"\n#include "decide.h"\n', 1)
anchor = '''  const size_t glue = SIZE_STACK (solver->levels);\n  assert (glue <= UINT_MAX);'''
replacement = '''  const size_t glue = SIZE_STACK (solver->levels);\n  assert (glue <= UINT_MAX);\n  if (!solver->probing)\n    kissat_v12_record_learned_clause (solver, (unsigned) glue);'''
if anchor not in s: raise SystemExit('learn.c anchor missing')
s = s.replace(anchor, replacement, 1)
p.write_text(s)

# 5) Free experimental storage cleanly.
p = root / 'internal.c'
s = p.read_text()
anchor = 'void kissat_release (kissat *solver) {\n  kissat_require_initialized (solver);\n'
replacement = anchor + '''  free (solver->v12_clause_lits);\n  free (solver->v12_clause_sizes);\n  free (solver->v12_clause_glues);\n  free (solver->v12_clause_epochs);\n'''
if anchor not in s: raise SystemExit('internal.c release anchor missing')
s = s.replace(anchor, replacement, 1)
p.write_text(s)

# 6) Print V12 counters in statistics builds for auditable intervention counts.
p = root / 'statistics.c'
s = p.read_text()
anchor = '  METRICS_COUNTERS_AND_STATISTICS\n\n#undef COUNTER\n'
replacement = '''  METRICS_COUNTERS_AND_STATISTICS\n\n  printf ("c v12_seen_conflicts: %" PRIu64 "\\n", solver->v12_seen_conflicts);\n  printf ("c v12_stored_clauses: %" PRIu64 "\\n", solver->v12_stored_clauses);\n  printf ("c v12_stored_literals: %" PRIu64 "\\n", solver->v12_stored_literals);\n  printf ("c v12_retrievals: %" PRIu64 "\\n", solver->v12_retrievals);\n  printf ("c v12_hint_uses: %" PRIu64 "\\n", solver->v12_hint_uses);\n  printf ("c v12_random_uses: %" PRIu64 "\\n", solver->v12_random_uses);\n  printf ("c v12_memory_resets: %" PRIu64 "\\n", solver->v12_memory_resets);\n\n#undef COUNTER\n'''
if anchor not in s: raise SystemExit('statistics.c anchor missing')
s = s.replace(anchor, replacement, 1)
p.write_text(s)

print('V12 patch applied')
