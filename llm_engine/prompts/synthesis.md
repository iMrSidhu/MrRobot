# Feature Synthesis (Model A)

You are analyzing the GitHub repository `{name}` for an autonomous
capability & security assessment. Judge by the CODE, not the prose.

Produce a JSON object with exactly these keys:

- "architecture": 2-4 sentences on the core architecture as evidenced by
  the file tree and entry-point structure.
- "marketing_claims": list of distinct capability claims made in the README.
- "verified_reality": list of what the code actually provides for those
  claims; cite file names from the tree where possible.
- "gaps": list of claims that are unverified, partially verified, or
  contradicted by the code.
- "capability_tags": 4-10 short lowercase tags for what the project can do
  (e.g. "web-scraping", "llm-orchestration").

When the README promises more than the entry points show, record that in
"gaps". If a section says its content is a compressed dossier, treat the
bullets as representative, not exhaustive.

## Directory tree
{tree}

## README excerpts
{readme}

## Entry-point structure
{code}
