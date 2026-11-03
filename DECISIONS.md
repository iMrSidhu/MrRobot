# DECISIONS

<!-- One entry per non-obvious choice:
- **<decision>** — context → decision → consequence  (step NN)
-->
- **Workflow scaffolding** — need auditable, restorable steps → checkpoint tags + rollback scripts under AGENT_PROTOCOL.md (step 00)
- **Optional AST parser** — design listed it as core tech, but slow-decode hardware only *benefits* from summaries → single flag `AST_SUMMARY` (default 1) gates just the entry-point summarize pass; off and unparseable share one raw-text fallback, so the AST is an accelerator, not a dependency (audit follow-up, DESIGN v1.1)
- **Explicit `security_json_path` DB column** — the API had guessed the security JSON as the sibling of `synthesis_path`; a real row pointed outside the repo and the guess silently returned nothing. One path per artifact in one table (DESIGN v1.2); old databases gain the column on next `init_db`, so legacy rows honestly show "no security results" until re-analyzed
