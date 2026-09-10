#!/usr/bin/env python3
from pathlib import Path

p=Path('kissat-rel-4.0.4/src/decide.c')
s=p.read_text()
needle='#include <inttypes.h>\n'
insert=r'''#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

/* SAT-RAG V11b experimental confidence-gated phase hints.
   Inert unless KISSAT_V11_HINTS points to a text file with rows:
     <1-based-var> <phase:-1|1> <confidence:0..1>
   Existing target/saved phases keep priority. Hints only replace the
   ordinary INITIAL_PHASE fallback when confidence >= threshold. */
static bool v11_hints_loaded = false;
static signed char *v11_phase_hints = 0;
static float *v11_phase_confidence = 0;
static unsigned v11_phase_hint_vars = 0;
static double v11_phase_threshold = 1.1;

static void v11_load_phase_hints (kissat *solver) {
  if (v11_hints_loaded)
    return;
  v11_hints_loaded = true;

  const char *path = getenv ("KISSAT_V11_HINTS");
  if (!path || !*path)
    return;

  const char *threshold = getenv ("KISSAT_V11_THRESHOLD");
  if (threshold && *threshold)
    v11_phase_threshold = atof (threshold);
  else
    v11_phase_threshold = 0.85;

  FILE *file = fopen (path, "r");
  if (!file)
    return;

  v11_phase_hint_vars = VARS;
  v11_phase_hints = calloc (VARS, sizeof *v11_phase_hints);
  v11_phase_confidence = calloc (VARS, sizeof *v11_phase_confidence);
  if (!v11_phase_hints || !v11_phase_confidence) {
    fclose (file);
    return;
  }

  unsigned var, loaded = 0;
  int phase;
  double confidence;
  while (fscanf (file, "%u %d %lf", &var, &phase, &confidence) == 3) {
    if (!var || var > VARS || !phase)
      continue;
    const unsigned idx = var - 1;
    v11_phase_hints[idx] = phase < 0 ? -1 : 1;
    v11_phase_confidence[idx] = (float) confidence;
    loaded++;
  }
  fclose (file);
  fprintf (stderr,
           "c V11b loaded %u phase hints, confidence threshold %.3f\n",
           loaded, v11_phase_threshold);
}

static int v11_confident_phase_hint (kissat *solver, unsigned idx) {
  v11_load_phase_hints (solver);
  if (!v11_phase_hints || idx >= v11_phase_hint_vars)
    return 0;
  if (v11_phase_confidence[idx] < v11_phase_threshold)
    return 0;
  return v11_phase_hints[idx];
}
'''
if needle not in s:
    raise SystemExit('include anchor not found')
s=s.replace(needle,insert,1)
needle2='''  if (!res) {\n    res = INITIAL_PHASE;\n    LOG ("%s uses initial decision phase %d", LOGVAR (idx), (int) res);\n    INC (initial_decisions);\n  }'''
replace2='''  if (!res) {\n    const int hint = v11_confident_phase_hint (solver, idx);\n    if (hint) {\n      res = hint;\n      LOG ("%s uses V11b phase hint %d", LOGVAR (idx), (int) res);\n    }\n  }\n\n  if (!res) {\n    res = INITIAL_PHASE;\n    LOG ("%s uses initial decision phase %d", LOGVAR (idx), (int) res);\n    INC (initial_decisions);\n  }'''
if needle2 not in s:
    raise SystemExit('phase anchor not found')
s=s.replace(needle2,replace2,1)
p.write_text(s)
print('patched',p)
