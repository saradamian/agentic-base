# Check a comparison

Because the record names the scorer and the reason a run has no verdict, two checks follow from
it. They also read logs you already have, with no server, database or token:

```bash
pip install surf-agentic-base
python -m agentic_base.demo --jsonl > results.jsonl   # forty example runs; or use a log of your own
agentic-base check results.jsonl --arm config
```

```text
baseline: assessed 20; excluded 1 (1 timeout); analysed 19
with-planner: assessed 20; excluded 6 (6 timeout); analysed 14
not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
outcomes: 27 name a citable scorer, 4 diagnostic, 2 name none
```

- **Did the comparison lose runs unevenly?** One agent resolves 85.7% and another 52.6%. The first
  also timed out on six hard tasks, the second on one, and a timeout has no verdict. Count every
  run and the gap is 60% against 50%. The check finds this, with a 95% interval, and shows the
  per-arm accounting clinical trials publish as the CONSORT flow diagram.
- **Who scored each outcome?** The benchmark's own harness and a person can be cited. The agent
  grading itself, another model's score and a user's thumbs-up are worth keeping and are not
  results. The check counts how many verdicts fall in each class.

`agentic-base check` reads JSONL (one JSON object per run; `--arm`, `--item`, `--verdict`,
`--channel` and `--scorer` name the fields), CSV with a header row, or an Inspect AI
`.eval`/`.json` log. Runs kept in MLflow read through its own export: save
`mlflow.search_runs(...).to_csv("runs.csv")` and pass `--arm params.config --item params.task
--verdict metrics.resolved`. A row with no verdict is counted as an exclusion, never silently
analysed. The exit code gates a CI job: **0** sound, **1** not sound, **2** when the input cannot
answer either way. `--json` prints the full report. In CI, after the job that writes the results:

```yaml
comparison-is-sound:
  image: python:3.12
  script:
    - pip install surf-agentic-base
    - agentic-base check results.jsonl --arm config
  allow_failure:
    exit_codes: [2]   # too little data yet: say so, do not block
```

## How large the difference is

Name one arm as the baseline, and the check also says how far each other arm is from it and how
sure that is. The verdict line and the exit code do not change.

```bash
agentic-base check results.jsonl --arm config --baseline baseline
```

```text
baseline: assessed 20; excluded 1 (1 timeout); analysed 19
with-planner: assessed 20; excluded 6 (6 timeout); analysed 14
not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
with-planner vs baseline, 14 tasks both scored: +14.3 pp (95% interval -9.8 to +38.0 pp), exact McNemar p = 0.50
  inconclusive: these pairs can only detect 28 pp or more
  excluded runs as failures, 20 tasks: +10.0 pp, p = 0.50
  assuming nothing about the 7 excluded runs, the difference lies between +5.0 and +40.0 pp and keeps its sign
outcomes: 27 name a citable scorer, 4 diagnostic, 2 name none
```

An excluded run has no outcome, so the difference is given three ways:

- **Tasks both arms scored.** The difference, its 95% interval and McNemar's exact test. Both
  arms faced the same tasks. Both arms finished them, so they lean easy. The number compares the
  two arms on these tasks.
- **Excluded runs counted as failures.** Every task either arm attempted. This reading is lowest
  for the arm with more exclusions.
- **Assumption-free bounds.** Every excluded outcome set to its worst value, then to its best. A
  sign inside these bounds holds whatever the excluded runs would have done.

The bounds describe these tasks. The interval describes what to expect on new ones. In the example
both are right. Whatever the timeouts hid, the planner resolves more of these twenty tasks.
Fourteen pairs with two disagreements are too few to say the same of other tasks.

When the interval spans zero, the line gives the smallest difference the pairs could have
detected. A reader then knows how large an effect could have gone unseen. When the interval sits
inside the equivalence margin, the arms are reported as equivalent. The margin is five percentage
points by default. `AP_CONTRAST_EQUIVALENCE_MARGIN` changes it, and the change belongs in the plan
before any result is read.

A task with more than one run in an arm stops the contrast, and the line says so. Choose the run to
count before checking. With more than two arms, each is compared with the baseline, and each line
carries Holm's correction. `--json` adds the contrasts to the report. The same functions are in
`agentic_base.domain.contrast` for use from Python.

`examples/is_this_comparison_sound.py` runs the same check from Python over a record type of its
own, through `agentic_base.domain.validity` and `agentic_base.domain.outcomes`:

```text
1. The number people report: resolved, over runs that finished
   baseline      10/19 = 52.6%
   with-planner  12/14 = 85.7%

2. What the validity check says
   not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
   examined 40 runs, 2 arms, 1 exclusion channel(s); could have flagged: True

3. The per-arm flow the verdict rests on
   baseline: assessed 20; excluded 1 (1 timeout); analysed 19
   with-planner: assessed 20; excluded 6 (6 timeout); analysed 14

4. Two honest numbers instead of one flattering one
   every run, a timeout counted as unresolved:
   baseline      10/20 = 50.0%
   with-planner  12/20 = 60.0%
   only the 14 tasks both arms finished:
   baseline      10/14 = 71.4%
   with-planner  12/14 = 85.7%

5. Which verdicts may be cited
   the benchmark's own harness        citable: True
   a quick in-tree check              citable: False
   the harness, but it failed open    citable: False
   the agent grading itself           citable: False
```
