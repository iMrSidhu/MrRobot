# Feature Synthesis (Model A)

You are analyzing the GitHub repository `{name}` for an autonomous
capability assessment. The input is the README only — the code cross-check
("verified_reality" and "gaps") is deliberately OFF for now; do not invent
those fields.

Produce a JSON object with exactly these keys:

- "architecture": 2-4 sentences on the core architecture as implied by the
  README's own description of itself.
- "marketing_claims": list of distinct capability claims made in the README.
- "capability_tags": 4-10 short lowercase tags for what the project claims
  it can do (e.g. "web-scraping", "llm-orchestration").

"verified_reality" and "gaps" may be omitted — they default to empty lists.
If a section says its content is a compressed dossier, treat the bullets as
representative, not exhaustive.

## README excerpts
{readme}
