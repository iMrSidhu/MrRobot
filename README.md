# GitHub Capability & Security Sentinel

Autonomous scanner that discovers high-impact AI GitHub repos, clones them safely (read-only),
runs dual local-LLM capability + security pipelines, writes Markdown briefings to `vault/`,
and streams results to a local dashboard. Design: `docs/DESIGN.md` — work rules: `AGENT_PROTOCOL.md`.

## Local setup

1. **Install & start Ollama** — <https://ollama.com/download> (Windows installer runs a tray
   server; or start with `ollama serve`).
2. **Respect the 6GB VRAM budget** (DESIGN.md §2.3) — set these where Ollama runs:
   - `OLLAMA_MAX_LOADED_MODELS=1` — only one model resident at a time.
   - `OLLAMA_KEEP_ALIVE=2m` — unload quickly after each call.
   (Windows: System → Advanced system settings → Environment Variables, or `setx` in a terminal,
   then restart the Ollama app.)
3. **Pull the pipeline models** (defaults from `shared/config.py`):
   ```
   ollama pull qwen2.5-coder:3b   # Model A — capability synthesis
   ollama pull phi3:mini          # Model B — security audit
   ```
4. **Verify readiness**:
   ```
   python scripts/check_ollama.py           # server + models + latency + VRAM report; non-zero exit on problems
   python scripts/check_ollama.py --pull    # auto-fetch missing models first
   ```
5. **Python deps**: `python -m venv .venv` then install `requirements.txt` (or at minimum
   `httpx python-dotenv pytest` to run the tests).
