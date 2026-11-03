# Agent Protocol

Rules for every agent (human or AI) working on this repository, step by step.

a) Before any work, read `docs/DESIGN.md`, `PROGRESS.md` and the prompt file for the current step.

b) Do only the current step. If the design looks wrong or ambiguous, write it under 'Open questions' in `PROGRESS.md`, pick the simplest option, and continue.

c) Services stay independent: no service imports another service's internals, only `shared/` (db, config, models).

d) Write small tests for every module and run them before checkpointing.

e) Never execute code from cloned repositories; only read files as text.

f) Update `PROGRESS.md` and the status row in `prompts/INDEX.md`.

g) Finish by running `scripts/checkpoint.sh <step-id> '<message>'`.

h) Never force-push, rewrite history, or delete tags.
