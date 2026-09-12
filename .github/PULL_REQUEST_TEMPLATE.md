## What changes, and what does not

<!-- One behaviour per pull request. Say what is deliberately left for a follow-up. Do not oversell:
     a reviewer who finds the claim broader than the diff stops trusting the rest. -->

Closes #

## How it was verified

- [ ] `uv sync --group dev --extra service` then `ruff check`, `ruff format --check`, `mypy src tests`
- [ ] `pytest tests -q` **with no `-W` flag**. The repository treats warnings as errors; a run that ignores them is not a run.
- [ ] Any new guard was broken on purpose and seen to fail before it was trusted.

## Portability

- [ ] If a module in `tests/test_portable_surface.py` changed: it still imports on 3.10 with only the four library dependencies.
- [ ] No site-specific value in code, chart defaults or the Dockerfile. Those belong in a deployment overlay.

## Risk

| Question | Answer (write N/A explicitly) |
|---|---|
| Schema or stored record changed? | |
| Public interface changed? | |
| New dependency? | |
| Touches URL fetching, secrets, or code execution? | |
