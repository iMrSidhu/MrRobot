# DECISIONS

<!-- One entry per non-obvious choice:
- **<decision>** — context → decision → consequence  (step NN)
-->
- **Workflow scaffolding** — need auditable, restorable steps → checkpoint tags + rollback scripts under AGENT_PROTOCOL.md (step 00)
- **Optional AST parser** — design listed it as core tech, but slow-decode hardware only *benefits* from summaries → single flag `AST_SUMMARY` (default 1) gates just the entry-point summarize pass; off and unparseable share one raw-text fallback, so the AST is an accelerator, not a dependency (audit follow-up, DESIGN v1.1)
