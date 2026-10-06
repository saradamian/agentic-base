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
