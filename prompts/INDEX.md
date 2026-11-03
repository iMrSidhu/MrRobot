# Step Prompts Index

Prompt file per step lives at `prompts/<step>-<slug>.md` (created when the step is prepared).

| Step | Title | Design refs | Status | Tag |
|------|-------|-------------|--------|-----|
| 01 | Skeleton & config | §5 Phase 1 (1.1), §4 | done | restore/01-r2 |
| 02 | Ollama check | §5 Phase 1 (1.2), §4 | done | restore/02 |
| 03 | DB & shared contracts | §5 Phase 1 (1.3), §2 | done | restore/03 |
| 04 | GitHub client | §5 Phase 2 (2.1) | done | restore/04 |
| 05 | Ingestion service | §5 Phase 2 (2.1–2.3), §3 (1) | done | restore/05 |
| 06 | Safe clone | §5 Phase 3 (3.1), §3 (2) | done | restore/06 |
| 07 | File filter | §5 Phase 3 (3.2) | todo | — |
| 08 | Tree & chunker | §5 Phase 3 (3.3) | todo | — |
| 09 | Processor service | §5 Phase 3, §2 (isolation) | todo | — |
| 10 | LLM client | §4, §2 (VRAM semaphore) | todo | — |
| 11 | Synthesis worker | §5 Phase 4 (Model A), §3 (3) | todo | — |
| 12 | Security worker | §5 Phase 4 (Model B), §3 (3) | todo | — |
| 13 | Analysis service | §5 Phase 4, §2 (circuit breaking) | todo | — |
| 14 | Report generator | §5 Phase 5 (5.1), §3 (4) | todo | — |
| 15 | FastAPI + SSE | §5 Phase 5 (5.2), §3 (5) | todo | — |
| 16 | Streamlit dashboard | §5 Phase 5 (5.3) | todo | — |
| 17 | Runner & end-to-end | §2, §3 (full flow) | todo | — |

Status values: `todo` → `in-progress` → `done` (with Tag filled in, e.g. `restore/05`).
