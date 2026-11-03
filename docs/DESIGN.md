---

## 1. Overview

The **GitHub Capability & Security Sentinel** is an autonomous, event-driven intelligence system designed for the **PS-02: Zero-Prompt AI ("Kill the Chatbox")** challenge. Instead of waiting for a manual user prompt, the system continuously scans GitHub for high-impact repositories ($>1,000$ stars) utilizing AI or agentic frameworks. 

Once a matching repository is identified, the system autonomously clones it, extracts core structural elements, runs **dual local LLM pipelines** (one for capability synthesis and one for security auditing), generates structured Markdown reports, and streams telemetry and insights directly to a live command center dashboard—all executed locally leveraging a 40GB system RAM and 6GB NVIDIA VRAM setup.

---

## 2. Microservices-Like Architecture & Failure Isolation

To prevent cascading failures (e.g., if GitHub rate-limits or a massive repo crashes a parser, the whole system shouldn't die), the architecture is decoupled into **isolated modular workers** communicating via asynchronous queues and local persistent storage (SQLite).

```
+-----------------------------------------------------------------------------------+
|                         MICROSERVICES ISOLATION TOPOLOGY                          |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +-------------------+      SQLite Queue      +--------------------------------+  |
|  | Ingestion Service | ---------------------> | Repository Processor Service   |  |
|  | (GitHub API Poller|                        | (Git Clone, AST/Tree Extractor)|  |
|  +-------------------+                        +--------------------------------+  |
|                                                               |                   |
|                                                    (Extracted Code Chunks)        |
|                                                               v                   |
|  +-------------------+                        +--------------------------------+  |
|  | Dashboard Service | <--------------------- | Dual LLM Analysis Engine       |  |
|  | (FastAPI + SSE    |    (Live Telemetry &   | [Model A: Feature Synthesis]   |  |
|  |  Streamlit HUD)   |     Markdown Artifact) | [Model B: Security Audit]      |  |
|  +-------------------+                        +--------------------------------+  |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

### Isolation & Fault-Tolerance Principles:
1. **Service Independence:** Each module runs as an independent asynchronous background task or process. If the GitHub API throws a rate-limit error, the Ingestion Service pauses gracefully without affecting the LLM inference engine or dashboard.
2. **Circuit Breaking on LLM Parsing:** If a repository's codebase contains malformed files or causes an Ollama timeout, the extraction error is caught locally, logged to the dashboard as a `FAILED_AUDIT` event, and the worker drops it to process the next queue item.
3. **VRAM Resource Serialization:** Because VRAM is bounded at 6GB, the Dual LLM Engine uses a semaphore lock to sequence Model A (Synthesis) and Model B (Security) executions, ensuring zero out-of-memory (OOM) crashes.

---

## 3. End-to-End System Flow Diagram

```
[Cron / Timer Trigger] 
       │
       ▼
1. Ingestion Service ──(New Repo >1k Stars found?)──► [No] ──► Wait & Retry
       │ [Yes]
       ▼
2. Processor Service (Clone Repo to /tmp, strip lockfiles/tests, parse README & entry points)
       │
       ▼
3. Dual LLM Pipeline (Sequential execution via Ollama to respect 6GB VRAM)
   ├──► [Worker A] Synthesis LLM (`qwen2.5-coder:3b`) ──► Extracts Marketing vs. Reality & Capabilities
   └──► [Worker B] Security LLM (`phi3:mini` or `qwen2.5-coder:1.5b`) ──► Scans for Vulnerabilities & Mitigations
       │
       ▼
4. Artifact Generator (Compiles structured Markdown report & saves to local Vault)
       │
       ▼
5. Dashboard Service (Pushes live events via Server-Sent Events / SSE to Streamlit UI HUD)
```

---

## 4. Tech Stack

* **Language:** Python 3.10+ (Asyncio, FastAPI, GitPython)
* **Local Inference Runtime:** Ollama (running lightweight, high-performance local models optimized for 6GB VRAM: e.g., `qwen2.5-coder:3b` for synthesis and `phi3:mini` or `qwen2.5-coder:1.5b` for security auditing).
* **Database & State Management:** SQLite + Local JSON/Markdown file store (leveraging the 40GB system RAM for in-memory caching and fast retrieval).
* **Dashboard / UI:** Streamlit (for rapid 12-hour deployment of a live command center HUD) + Server-Sent Events (SSE) for real-time telemetry streaming.
* **Code Processing:** `pathlib` for lightweight directory tree flattening, plus an **optional** Python AST parser that summarizes entry points (`AST_SUMMARY=1` default; `=0` feeds raw entry-point text). The parser is never a hard dependency — off or unparseable files always fall back to raw text.

---

## 5. Step-by-Step Implementation Plan

### Phase 1: Environment & Orchestration Setup
* **Step 1.1:** Initialize project directory structure (`/ingestion`, `/processor`, `/llm_engine`, `/dashboard`, `/vault`).
* **Step 1.2:** Configure Ollama locally and pull required models (`qwen2.5-coder:3b` and `phi3:mini`) to verify VRAM footprint.
* **Step 1.3:** Setup SQLite schema (`repositories` table tracking: `id`, `name`, `stars`, `status`, `synthesis_path`, `security_report_path`, `timestamp`).

### Phase 2: Ingestion Service (The Event Radar)
* **Step 2.1:** Build a polling loop using the GitHub REST/GraphQL API targeting keywords (`ai agent`, `harness`, `autonomous`, `llm framework`) with `stars:>1000`.
* **Step 2.2:** Implement local database deduplication check so previously analyzed repositories are bypassed.
* **Step 2.3:** Push newly discovered target repositories into the processing queue.

### Phase 3: Repository Processor & Code Portioning
* **Step 3.1:** Implement a safe Git clone utility that clones repositories into an isolated `/tmp/repo_cache` directory, immediately wiping `.git` history to save disk space.
* **Step 3.2:** Write a filtering script to strip binary files, node_modules, lockfiles, and test directories, keeping only core source files and `README.md`.
* **Step 3.3:** Generate a flattened directory text tree and chunk core entry points to fit within LLM context windows.

### Phase 4: Dual LLM Pipeline (Synthesis + Security Auditing)
* **Model A (Synthesis Worker):**
  * *Prompt objective:* Analyze README chunks and source code structure to output: 1) Core architecture, 2) Marketing claims vs. verified code reality, and 3) Capability breakdown tags.
* **Model B (Security Audit Worker):**
  * *Prompt objective:* Scan source code files for critical vulnerability patterns (e.g., hardcoded secrets, unvalidated prompt injections, insecure deserialization, unhandled remote code execution vectors via tool use).
  * *Output generation:* Compiles findings into a structured vulnerability matrix including **Severity Level**, **Vulnerable File/Line**, **Description**, and **Suggested Mitigation Strategies**.

### Phase 5: Artifact Generation & Dashboard HUD
* **Step 5.1:** Automatically compile the outputs from Model A and Model B into a comprehensive, beautifully structured Markdown briefing file saved locally in `/vault`.
* **Step 5.2:** Build a FastAPI backend with Server-Sent Events (SSE) endpoints streaming real-time status updates from the queue.
* **Step 5.3:** Build a Streamlit Command Center dashboard featuring:
  * **Left Panel:** Live Event Radar / SSE Terminal feed.
  * **Center Panel:** Marketing vs. Reality Split Card & Capability Tag Cloud.
  * **Right/Bottom Panel:** Security Vulnerability Report & Mitigation Action Items.

## Change Log

- v1.0 - initial design
- v1.1 - AST parser downgraded to an optional component (`AST_SUMMARY` flag, default on); raw-text entry points are the baseline path
- v1.2 - security JSON path stored explicitly in `repositories.security_json_path` (auto-migrated); the dashboard API reads the column instead of guessing the `.security.json` sibling, and the HUD dossier/vulnerability panels live-refresh on a 2s timer
