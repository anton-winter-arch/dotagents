---
name: reference-catalog
description: Categorized catalog of AI-engineering tools, repos, docs, and resources folded into the ai-engineering skill. Curated by category; the exhaustive deduped URL set lives in link-ledger.md.
updated: 2026-07-27
---

# AI-Engineering Reference Catalog

Every loose link from the source bundle, **sorted by category**. One-line
descriptions appear only where the project is confidently known; genuinely
obscure repos sit in [To-triage](#to-triage--unverified) with the link only (no
invented descriptions). Doc-page *families* (Claude Code, Motion, Firecrawl,
LangChain, Agno, Crawl4AI) are represented by their canonical root here - the
full per-page set is preserved in `link-ledger.md`.

> Analysis, comparison tables, stars/licenses, and recommendations live in
> [`agent-stack-map.md`](agent-stack-map.md). This file is the *index*; that file
> is the *opinion*.

---

## Agent frameworks & SDKs

- [langchain-ai/langchain](https://github.com/langchain-ai/langchain) - broad LLM/agent framework; largest integration ecosystem. Docs: [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) (full page set in ledger).
- [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) - LangChain's deep/long-horizon agent pattern.
- [run-llama/llama_index](https://github.com/run-llama/llama_index) - data + agent framework over indices, graphs, retrievers.
- [openai/openai-agents-python](https://github.com/openai/openai-agents-python) - lightweight multi-agent SDK (tools, sessions, handoffs, tracing).
- [google/adk-python](https://github.com/google/adk-python) - Google Agent Development Kit. Docs: [adk.dev](https://adk.dev/2.0/).
- [google/agents-cli](https://github.com/google/agents-cli) - Google agents CLI. Docs: [google.github.io/agents-cli](https://google.github.io/agents-cli/).
- [microsoft/agent-framework](https://github.com/microsoft/agent-framework) - MS successor framework (Python/.NET). Docs: [learn.microsoft.com/agent-framework](https://learn.microsoft.com/en-us/agent-framework/).
- [strands-agents/sdk-python](https://github.com/strands-agents/sdk-python) - model-driven SDK with built-in MCP. Docs: [strandsagents.com](https://strandsagents.com/).
- [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) - programming-not-prompting; compiled LM pipelines.
- [Agno docs](https://docs.agno.com/introduction) - agents/teams/workflows/AgentOS runtime (full reference set in ledger).

## Agent harnesses & coding agents

_Terminal-agent landscape verified 2026-07-01 - see `agent-stack-map.md` Section B for the comparison table + cautions._

- [openai/codex](https://github.com/openai/codex) - OpenAI Codex CLI: Rust, sandboxed terminal coding agent, Apache-2.0 (~85k★).
- [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) - Google's open terminal agent, Apache-2.0 (~105k★). ⚠️ consumer access ends 2026-06-18 → Antigravity.
- [sst/opencode](https://github.com/sst/opencode) ([anomalyco/opencode](https://github.com/anomalyco/opencode)) - provider-agnostic OSS terminal agent (MIT, ~160–178k★); the 2026 OSS default. Site: [opencode.ai](https://opencode.ai/).
- [earendil-works/pi](https://github.com/earendil-works/pi) - Pi: minimal, self-extending BYOK harness (MIT). Fork: [can1357/oh-my-pi](https://github.com/can1357/oh-my-pi). Site: [pi.dev](https://pi.dev/).
- [cline/cline](https://github.com/cline/cline) - Plan/Act coding agent, IDE+CLI+SDK (8M+ users). Site: [cline.bot](https://cline.bot/).
- [Aider-AI/aider](https://github.com/Aider-AI/aider) - git-native terminal pair-programmer, Apache-2.0 (~46.8k★). ⚠️ cadence slowed (last push 2026-05-22).
- [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) - LangChain's batteries-included harness (MIT, ~25k★). JS: [deepagentsjs](https://github.com/langchain-ai/deepagentsjs).
- [charmbracelet/crush](https://github.com/charmbracelet/crush) - Charm's continuation of the original (archived) Go opencode.
- [Jules](https://jules.google/) - Google's proprietary async coding agent (GA I/O 2026); Jules Tools CLI + API.
- [Antigravity](https://antigravity.google/) - Google's proprietary agent-first IDE/platform 2.0 (desktop + CLI + SDK).
- [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) - autonomous software-engineering agent (formerly OpenDevin); 1.0 on [software-agent-sdk](https://github.com/OpenHands/software-agent-sdk).
- [bradAGI/awesome-cli-coding-agents](https://github.com/bradAGI/awesome-cli-coding-agents) - curated directory of terminal-native coding agents/harnesses (seed source).
- [aaif-goose/goose](https://github.com/aaif-goose/goose) - Block's open coding agent harness.
- [browser-use/browser-harness](https://github.com/browser-use/browser-harness) - browser-driving agent harness.
- [HKUDS/OpenHarness](https://github.com/HKUDS/OpenHarness) - pure-Python harness around tools/knowledge/observation/action/safety.
- [HKUDS/nanobot](https://github.com/HKUDS/nanobot) - ultra-lightweight personal agent with memory + sandboxing.
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) · [nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent) - Nous agent harness.
- [openclaw/openclaw](https://github.com/openclaw/openclaw) - self-hosted personal assistant controllable from chat apps.
- [Chachamaru127/claude-code-harness](https://github.com/Chachamaru127/claude-code-harness) - Claude Code harness pattern.
- [agentforce314/clawcodex](https://github.com/agentforce314/clawcodex) - Claude/Codex harness.
- [open-gitagent/gitagent](https://github.com/open-gitagent/gitagent) - git-native agent. Site: [gitagent.sh](https://www.gitagent.sh/).
- [omnigent-ai/omnigent](https://github.com/omnigent-ai/omnigent) - Databricks' **meta-harness**: runs Claude Code / Codex / Cursor / OpenCode / Hermes behind one orchestration API, adding OS-level sandboxing (bubblewrap/seatbelt) and stacked cost/access policies. Apache-2.0 (~7.2k★, checked 2026-07-14). ⚠️ self-described alpha, 571 open issues - pin versions.
- [alookai/alook](https://github.com/alookai/alook) - gives local coding agents email addresses, roles and an org chart so they route tasks to each other (email as the agent bus). Apache-2.0, TS (~0.9k★, checked 2026-07-14). ⚠️ v0.0.x; "self-hosted" is partial - the orchestrator component is Cloudflare-hosted; the shared-memory claim is undocumented/unverified.
- [xai-org/grok-build](https://github.com/xai-org/grok-build) - xAI's terminal coding agent: full-screen Rust TUI, plus headless mode for CI and editor integration over the Agent Client Protocol. Apache-2.0 (~22.8k★, checked 2026-07-27). ⚠️ Published as periodic squashed exports from an internal monorepo (1 contributor, 12 commits) - a vendor drop, not a community codebase; issues and PRs land against a snapshot.
- [andrewyng/openworker](https://github.com/andrewyng/openworker) - desktop agent that works across local files and 25+ connected apps (Slack, GitHub, Jira, Notion, Gmail), decomposing a task into steps and gating consequential actions behind approval. MIT, Python + React/TS with a Rust STT sidecar (~7.1k★, checked 2026-07-27). Open beta, 4 contributors, first published 2026-07-20 - worth reading as a reference implementation of human-in-the-loop approval gating on a desktop agent.
- [ogulcancelik/herdr](https://github.com/ogulcancelik/herdr) - terminal multiplexer for concurrent agents: one Rust binary showing every agent's state (blocked / working / done), sessions surviving detach and restart, and a socket API agents call to spawn their own panes. Apache-2.0 (~21.1k★, checked 2026-07-27). The tmux-shaped answer to running several harnesses at once; a plugin marketplace is bolted on, so vet extensions separately.
- [shepherd-agents/shepherd](https://github.com/shepherd-agents/shepherd) - runtime substrate that makes an agent run a reversible, git-like trace: fork, replay, and revert any execution, with syscall-level permission enforcement (macOS Seatbelt, Linux Landlock) and outputs held as reviewable proposals. MIT, Python 3.11+ (~1.6k★, checked 2026-07-27). ⚠️ Self-declared alpha, APIs changing; macOS/Linux only. The fork-and-replay idea is the reusable part.
- [EverMind-AI/Raven](https://github.com/EverMind-AI/Raven) - self-improving agent harness over [EverOS](https://github.com/EverMind-AI/EverOS) (its markdown-native local memory layer): durable user + agent memory, evolving skills, Agent Templates, a scheduler for proactive runs, and tracing. Apache-2.0, Python (~2.8k★, checked 2026-07-27). Backed by EverMind (Shanda Group). ⚠️ Pre-1.0 and pre-alpha by its own README; not on PyPI (install is a GitHub Release wheel); its memory benchmark claims are first-party.
- [taracodlabs/aiden](https://github.com/taracodlabs/aiden) - autonomous "work engine" driving files, terminal, browser and APIs from a prompt, bundling 76 skills and 121 tools across 19 providers. TypeScript/Node (~0.8k★, checked 2026-07-27). ⚠️ **AGPL-3.0 core** with paid commercial relicensing for closed-source use - a dual-license trap, not a permissive dependency. Solo-maintained (2 contributors).
- [patoles/agent-flow](https://github.com/patoles/agent-flow) - live visualization of a Claude Code or Codex run: an interactive node graph of the agent branching into subagents and tool calls, with a timeline and JSONL log replay. Apache-2.0, TS (~1.4k★, checked 2026-07-27). Debugging and post-mortem tooling for orchestration, adjacent to the eval stack below.
- [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering) - patterns, starters and CLI tools (`loop`, `loop-audit`, `loop-init`, `loop-cost`) for the discipline of *designing the loop an agent runs in* rather than the prompt - scheduled triage, CI sweeps, cost accounting - across Claude Code, Codex, Grok and others. MIT (~9.5k★, checked 2026-07-27). Half working code, half essays; the essays are the reason to read it.

## Memory & context systems

- [getzep/graphiti](https://github.com/getzep/graphiti) - temporal knowledge-graph memory.
- [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) - agent memory toolkit.
- [memodb-io/Acontext](https://github.com/memodb-io/Acontext) - self-learning context platform.
- [MemoriLabs/Memori](https://github.com/MemoriLabs/Memori) - SQL-native agent memory engine.
- [MemPalace/mempalace](https://github.com/MemPalace/mempalace) · [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace) - memory-palace store.
- [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) - human-like memory system.
- [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) - persistent code knowledge graph over MCP (see Code intelligence & navigation for the full entry).
- [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) - Claude memory daemon. Docs: [docs.claude-mem.ai](https://docs.claude-mem.ai/).
- [Gentleman-Programming/engram](https://github.com/Gentleman-Programming/engram) - memory/engram project.
- [matrixorigin/Memoria](https://github.com/matrixorigin/Memoria) - version-controlled agent memory: snapshot, branch, merge and roll back a memory store the way git does a repo, plus hybrid vector + full-text retrieval, contradiction detection and an audit trail on every mutation. Apache-2.0 (~0.5k★, checked 2026-07-27). ⚠️ Branching is implemented on **MatrixOne's** copy-on-write MVCC engine, so the headline feature carries a database dependency - not a drop-in store. Quiet since 2026-06-29; 1 watcher.
- [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS) - local-first, markdown-native portable memory layer underneath Raven (see Agent harnesses).

## Vector & graph databases

- [chroma-core/chroma](https://github.com/chroma-core/chroma) - embeddings/vector DB.
- [milvus-io/milvus](https://github.com/milvus-io/milvus) - scalable vector DB.
- [activeloopai/deeplake](https://github.com/activeloopai/deeplake) - multimodal "database for AI" / vector store.
- [falkordb/falkordb](https://github.com/falkordb/falkordb) - graph DB / GraphRAG substrate (**SSPL**).
- [HelixDB/helix-db](https://github.com/HelixDB/helix-db) - graph-vector DB.

## RAG / retrieval / knowledge engines

- [infiniflow/ragflow](https://github.com/infiniflow/ragflow) - deep-document RAG engine with agent features.
- [neuml/txtai](https://github.com/neuml/txtai) - embeddings DB + semantic search + LLM workflows.
- [VectifyAI/OpenKB](https://github.com/VectifyAI/OpenKB) - open knowledge-base builder.
- [stanford-oval/storm](https://github.com/stanford-oval/storm) - research/report synthesis from web sources.
- [LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research) - local deep-research pipeline.
- [Canner/WrenAI](https://github.com/Canner/WrenAI) - governed text-to-SQL for agents: a semantic layer (Modeling Definition Language capturing models, relationships, metrics and access policy) sits between the question and 20+ warehouses, so retrieval is schema-aware and answers are traceable to approved definitions rather than guessed joins. Python (~16.7k★, checked 2026-07-27). The pattern to steal when an agent must query a real warehouse: **model the semantics first, generate SQL second.** ⚠️ Multi-licensed by path - `core/`, `sdk/`, `skills/`, `examples/` are Apache-2.0, `docs/` is CC-BY-4.0, and the LICENSE pre-stages **AGPL-3.0** for future modules that do not exist yet (verified 2026-07-27). Re-read the path→license table before depending on any new subtree.

## Web & document ingestion

- [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) - scrape/crawl/extract/search for agents (AGPL). Docs: [docs.firecrawl.dev](https://docs.firecrawl.dev/introduction) (full feature set in ledger).
- [docling-project/docling](https://github.com/docling-project/docling) - complex-doc → structured agent-ready data.
- [Crawl4AI docs](https://docs.crawl4ai.com/) - LLM-friendly crawler → markdown/structured (full page set in ledger).
- [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling) - adaptive/stealth web scraping.
- [jsvine/pdfplumber](https://github.com/jsvine/pdfplumber) - PDF text/table extraction.
- [opendataloader-project/opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) - PDF data loading.
- [datalab-to/surya](https://github.com/datalab-to/surya) - OCR / layout / reading-order detection.
- [google/langextract](https://github.com/google/langextract) - structured extraction from text with LLMs.
- [tensorlakeai/tensorlake](https://github.com/tensorlakeai/tensorlake) - document ingestion / data for agents.
- [iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) - read/render/edit .docx/.xlsx/.pptx via a path-addressed DOM over OpenXML, no MS Office installed; CLI + MCP server, native formula engine, HTML/PNG render pass that closes the agent's render→look→fix loop. Apache-2.0, C# single binary (~16k★, checked 2026-07-14). ⚠️ installs via `curl | bash` and auto-writes a SKILL.md into detected agent clients - review before adoption.

## Skills, tool packs & MCP

- [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) - reusable agent skills collection.
- [NVIDIA/skills](https://github.com/NVIDIA/skills) - NVIDIA agent skills.
- [markdown-viewer/skills](https://github.com/markdown-viewer/skills) - skills pack.
- [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) - **canonical** Karpathy coding-guidelines framework: a `CLAUDE.md` (installable as a plugin) of four principles - Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution - derived from Karpathy's "LLM coding pitfalls". MIT (~192k★, checked 2026-07-14). A good base to adapt house coding rules from.
- [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) - a fork/mirror of the above (`multica-ai` is canonical); kept for provenance.
- [Agents365-ai/drawio-skill](https://github.com/Agents365-ai/drawio-skill) - draw.io diagram skill.
- [phuryn/pm-skills](https://github.com/phuryn/pm-skills) - product-management skills.
- [rohitg00/skillkit](https://github.com/rohitg00/skillkit) - skill authoring kit.
- [virgiliojr94/book-to-skill](https://github.com/virgiliojr94/book-to-skill) - convert books into skills.
- [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) - research skill: parallel retrieval across Reddit/X/YouTube/HN/GitHub/Polymarket, engagement-weighted ranking, cross-source dedupe → one cited brief. MIT (~52k★, checked 2026-07-14). Worth reading as a *pattern* for multi-source research skills, not just installing.
- [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) - 13 markdown skills that inject a frontend design method into coding agents so generated UIs stop reading as default-Tailwind AI slop. Method: infer a one-line "Design Read" from the brief → set explicit DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY dials → gate output behind a ~95-item mechanical anti-AI-tell checklist (countable rules; em-dash, Inter and pure `#000000` banned outright). MIT, prompt-only (~63k★, checked 2026-07-14). A reference exemplar of a **checklist-gated skill** - a design method encoded as mechanically countable rules rather than vibes; worth stealing the shape for any skill whose output is judged aesthetically. ⚠️ Verification is LLM self-check with **no evals/tests/CI**, so its quality claims are unfalsifiable; scoped to marketing surfaces (explicitly excludes dashboards/admin UI); skill content last changed 2026-06-12 despite recent README churn; README warns of crypto scammers piggybacking the name - vet lookalikes before installing.
- [affaan-m/ECC](https://github.com/affaan-m/ECC) - **canonical**; formerly `affaan-m/everything-claude-code`, renamed in place (same repo id, the old path 301-redirects; verified 2026-07-28). No longer a config bundle: it now bills itself as an agent-harness operating system, shipping 67 agents, 281 skills, 94 commands, 34+ rule sets, hooks across 20+ event types, a cross-session memory/instincts layer, and AgentShield. Installs as a Claude Code plugin marketplace (`/plugin marketplace add`), or via `install.sh --profile minimal|core|full --target <harness>` for Codex, Cursor, OpenCode, Gemini, Zed, Qwen, Kimi and others; Copilot gets an instruction-only layer. MIT, v2.1.0 released 2026-07-27 (~234.6k★, 98 open issues, checked 2026-07-28). Author is the original: created 2026-01-18, days before the wave of same-named repos. ⚠️ Sheer size is the caution - 281 skills is a trigger-collision surface, and a `full` profile install writes agents, hooks and rules across the harness config. Read it as a source of patterns and install profile-scoped, not wholesale. An `ECC Pro` hosted GitHub App is paid; the OSS repo is MIT.
- [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) - the former path; **redirects to `affaan-m/ECC`** (renamed, same repo - verified 2026-07-28). Kept for provenance.
- ⚠️ **Same-name lookalikes.** `WorldFlowAI/everything-claude-code` (~0.7k★, created 2026-01-23, single push, **no license file**) and several `-zh`/`-ios`/`-android`/`-mobile` spinoffs are copies or translations, not the source. The best-starred translation, `xu-xiang/everything-claude-code-zh` (MIT, ~1.8k★), states its provenance honestly. Match on `affaan-m` before citing or installing.
- [affaan-m/agentshield](https://github.com/affaan-m/agentshield) - security scanner for **agent configurations** rather than application code: audits agent/skill definitions, MCP server configs and tool permissions against a stated 102 rules, shipping as CLI, GitHub Action, ECC plugin and GitHub App. MIT, (~1.0k★, checked 2026-07-28). The closest off-the-shelf analogue to a hand-maintained agent-tooling security checklist; worth diffing its rule set against one rather than adopting it outright, since its rules and tests are first-party and unaudited.
- [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit) - Claude Code toolkit.
- [VILA-Lab/Dive-into-Claude-Code](https://github.com/VILA-Lab/Dive-into-Claude-Code) - Claude Code deep-dive.
- [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) - token-compression output style.
- [rtk-ai/rtk](https://github.com/rtk-ai/rtk) - Rust Token Killer; CLI output token optimizer.
- [rohitg00/kubectl-mcp-server](https://github.com/rohitg00/kubectl-mcp-server) - kubectl MCP server.

## Eval, tracing & observability

- [confident-ai/deepeval](https://github.com/confident-ai/deepeval) - LLM eval framework.
- [openai/evals](https://github.com/openai/evals) - OpenAI eval harness.
- [comet-ml/opik](https://github.com/comet-ml/opik) - LLM tracing/eval/observability.
- [mlflow/mlflow](https://github.com/mlflow/mlflow) - experiment tracking, model registry, GenAI tracing.
- [wandb/wandb](https://github.com/wandb/wandb) - experiment tracking / Weave LLM tracing.
- [Giskard-AI/giskard-oss](https://github.com/Giskard-AI/giskard-oss) - evals, red-teaming and test generation for agentic systems: scenario APIs with LLM-as-judge (Checks), an adversarial vulnerability scanner (Scan), and RAG evaluation with synthetic data generation (planned). Apache-2.0, Python 3.12+ (~5.7k★, checked 2026-07-27). Giskard **v3 is a fresh rewrite** built for multi-turn agent testing, not a rename - v2 still exists and is no longer actively maintained, so pin the package you mean.
- [patoles/agent-flow](https://github.com/patoles/agent-flow) - visual replay of an agent run's branching and tool calls (see Agent harnesses).

## Fine-tuning, RL & training

- [unslothai/unsloth](https://github.com/unslothai/unsloth) - fast local fine-tuning + RL for open models.
- [OpenPipe/ART](https://github.com/OpenPipe/ART) - agent reinforcement trainer: RL over multi-step agent trajectories with rewards scored by an LLM judge, so a task needs no hand-written reward function. Apache-2.0, Python (~10.5k★, checked 2026-07-27).
- [microsoft/agent-lightning](https://github.com/microsoft/agent-lightning) - framework-agnostic agent RL / prompt optimization / SFT.
- [NVIDIA-NeMo/labs-molt](https://github.com/NVIDIA-NeMo/labs-molt) - Molt: agentic-first RL research framework - fully async, multi-turn, multimodal, on Ray + vLLM rollouts + FSDP2 training, scaling to trillion-parameter MoE. Apache-2.0, Python (~0.6k★, checked 2026-07-27). Deliberately small (~9.2K lines of RL-specific code) and meant to be read and forked. NVIDIA **labs** - research code, not a supported NeMo product.
- [FareedKhan-dev/train-llm-from-scratch](https://github.com/FareedKhan-dev/train-llm-from-scratch) - educational LLM training.

## Code intelligence & navigation

_Repo → queryable knowledge graph is the most crowded category in this catalog; `agent-stack-map.md` Section I carries the comparison table, the shared caveats, and the pick._

- [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) - GraphRAG for codebases: deterministic tree-sitter parse (no LLM for code) + Leiden community detection → a graph an agent queries instead of grepping. Also ingests docs, SQL schemas, configs and PDFs, but those go through an LLM pass. Emits `graphify-out/` (`graph.json`, `graph.html`, `GRAPH_REPORT.md`, optional Obsidian vault / GraphML / Neo4j / SVG); ships as CLI + optional MCP server + `/graphify` skill. Apache-2.0, Python (~97.6k★, 676 open issues, checked 2026-07-28). Ships on PyPI as **`graphifyy`** (CLI stays `graphify`), 0.9.29 as of 2026-07-28, `requires-python >=3.10`; default branch is **`v8`**, not `main`. Core install is 3 libraries (networkx, numpy, rapidfuzz) plus ~28 pinned tree-sitter grammars; everything else is an extra (`mcp`, `pdf`, `watch`, `svg`, `neo4j`, `falkordb`, `video`, `office`, `leiden`, and one per model provider). ⚠️ Star count is a hype signal, not a quality one - pre-1.0, and the org is anonymous with no public members. The "nothing leaves your machine" claim holds for **code** parsing only; doc/PDF/media extraction calls a model - Gemini if `GEMINI_API_KEY`/`GOOGLE_API_KEY` is set, otherwise the host coding agent does it by fanning out `general-purpose` subagents, which spends session tokens rather than an API bill. ⚠️ Leiden clustering needs the `leiden` extra (`graspologic`), which pins to **Python < 3.13**. ⚠️ `graphify install` is not just a skill drop: it writes `~/.claude/skills/graphify/`, injects an always-on block into `CLAUDE.md`, and registers PreToolUse hooks on `Bash|Grep` and `Read|Glob` in `settings.json` (with a `--strict` mode that blocks raw reads until a graphify query has run). Use `--project` to scope it, and diff before accepting the global variant.
- [safishamsi/graphify](https://github.com/safishamsi/graphify) - the project's former path; **redirects to `Graphify-Labs/graphify`** (renamed, same repo - verified 2026-07-27). Kept for provenance; earlier notes here treating the two as different projects were wrong.
- [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) - local-first tree-sitter parse into a persistent SQLite graph of functions, call chains, imports and blast radius, served over MCP; tracks changes incrementally so a review only pulls the affected slice. MIT, Python (~26.7k★, checked 2026-07-27). Narrower than graphify by design - code only, aimed squarely at review and large-repo navigation. Its 82x median token-reduction figure is first-party.
- [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) - MCP server indexing a repo into a persistent graph of functions, classes, call chains, HTTP routes and cross-service links via 15 tools; tree-sitter across ~158 languages with LSP type resolution for ~11 of them. Single static binary, zero dependencies. MIT, C (~35.7k★, checked 2026-07-27). The only entrant with a public write-up ([arXiv 2603.27277](https://arxiv.org/html/2603.27277v1)) - and it reports a **tradeoff**, not a free win: 83% answer quality against 92% for a plain file-exploring agent, at ~10x fewer tokens.
- [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) - pre-indexed tree-sitter + SQLite/FTS5 code graph that auto-syncs on file change, targeting Claude Code, Codex, Gemini, Cursor, OpenCode, Kiro and Hermes. MIT (~62.6k★, checked 2026-07-27). Releases from 2026-07 onward carry build attestations verifiable with `gh attestation verify` - the strongest supply-chain signal in this group.
- [adithya-s-k/GitVizz](https://github.com/adithya-s-k/GitVizz) - repo visualization/understanding. ⚠️ No license file and untouched since 2026-02-12 - unlicensed means all rights reserved; do not vendor.
- [repowise-dev/repowise](https://github.com/repowise-dev/repowise) - repo intelligence: code-health scores, generated docs, git analytics (**AGPL-3.0**).
- [alibaba/open-code-review](https://github.com/alibaba/open-code-review) - automated code review.
- [braedonsaunders/codeflow](https://github.com/braedonsaunders/codeflow) - code-flow tooling.
- [langchain-ai/openwiki](https://github.com/langchain-ai/openwiki) - generates and *incrementally maintains* a markdown wiki for a repo (GitHub Action diffs new commits), then points AGENTS.md/CLAUDE.md at it so agents read docs instead of burning context rediscovering the codebase. MIT (~11k★, checked 2026-07-14). ⚠️ 0.1.x, three weeks old. Personal mode (Gmail/Notion/GitHub connectors) doubles as a memory store.

## Model serving, inference & routing

- [superlinked/sie](https://github.com/superlinked/sie) - Superlinked Inference Engine: one self-hosted cluster serving 100+ open models with on-demand loading behind a single API, covering search/retrieval, document→markdown conversion, structured output, content safety and agent-loop execution. Apache-2.0, Rust + Python + TS (~2.3k★, checked 2026-07-27). The consolidation play when a stack has accumulated a separate server per model; heavier than Ollama and aimed at a cloud cluster, not a laptop.
- [ollama/ollama](https://github.com/ollama/ollama) - local model serving. Docs: [docs.ollama.com tool-calling](https://docs.ollama.com/capabilities/tool-calling), [tool support](https://ollama.com/blog/tool-support).
- [LMCache/LMCache](https://github.com/LMCache/LMCache) - KV-cache / inference acceleration. Site: [lmcache.ai](https://lmcache.ai/).
- [OpenRouter](https://openrouter.ai/) - cloud model routing.
- [Brave Search API](https://brave.com/search/api/) - search provider for agents.
- [kyutai-labs/pocket-tts](https://github.com/kyutai-labs/pocket-tts) - 100M-param open-weights TTS: ~6x real-time on CPU (no GPU), ~200ms first chunk, voice cloning from ~5s, 6 languages; ships a pip library, CLI and local streaming server. MIT (~7.5k★, checked 2026-07-14). The local-serving tier for a voice agent; benchmarks are vendor-reported.

## Frontend / app builders

- [copilotkit/copilotkit](https://github.com/copilotkit/copilotkit) - in-app copilot UI + AG-UI protocol.
- [mintplex-labs/anything-llm](https://github.com/mintplex-labs/anything-llm) - all-in-one private RAG/agent app.
- [Avaiga/taipy](https://github.com/Avaiga/taipy) - Python data/AI app builder.
- [presenton/presenton](https://github.com/presenton/presenton) - AI presentation generation.
- [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) - design-taste skill pack for agent-generated UIs (see Skills, tool packs & MCP for the method + caveats).

## Privacy, security & red-team

- [openai/privacy-filter](https://github.com/openai/privacy-filter) - PII detection/masking. [Announcement](https://openai.com/index/introducing-openai-privacy-filter/) · [forum](https://community.openai.com/t/openai-privacy-filter-for-detecting-and-masking-pii-in-text/1379537).
- [zeroc00I/LLM-anonymization](https://github.com/zeroc00I/LLM-anonymization) - LLM anonymization.
- [usestrix/strix](https://github.com/usestrix/strix) - autonomous security/pentest agents.
- [google/magika](https://github.com/google/magika) - ML file-type detection.
- [elder-plinius/T3MP3ST](https://github.com/elder-plinius/T3MP3ST) - multi-agent offensive-security meta-harness: drives existing coding agents as interchangeable backends through an 8-operator kill-chain of ReAct subagents. AGPL-3.0, TS (~4.7k★, checked 2026-07-14). Catalogued for the *engineering* pattern - a meta-harness plus `verify-claims`, which recomputes its reported pass@1 from committed artifacts (a rare and worth-stealing eval idea). ⚠️ Dual-use: authorized-testing-only offensive tooling, AGPL is viral - reference material, not a dependency. Its headline benchmark numbers are self-reported and unverified. (Owner is known for jailbreak corpora; this repo is *not* one - verified 2026-07-14 at repo/DeepWiki level, not file-by-file.)

## Learning, awesome-lists & references

- [Shubhamsaboo/awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) - curated LLM apps.
- [Sumanth077/ai-engineering-toolkit](https://github.com/Sumanth077/ai-engineering-toolkit) - AI-engineering toolkit list.
- [rohitg00/ai-engineering-from-scratch](https://github.com/rohitg00/ai-engineering-from-scratch) - build-from-scratch curriculum.
- [microsoft/AI-Engineering-Coach](https://github.com/microsoft/AI-Engineering-Coach) - learning agent.
- [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) - agent governance.
- [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog) - KB catalog ([okf SPEC](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)).
- [github/spec-kit](https://github.com/github/spec-kit) - spec-driven development kit.
- [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering) - patterns and essays on designing the loop rather than the prompt (see Agent harnesses).
- [liquidslr/system-design-notes](https://github.com/liquidslr/system-design-notes) - system-design reference.
- [datasciencedojo LLM wiki tutorial](https://datasciencedojo.com/blog/llm-wiki-tutorial/).

## Research papers

- [arxiv 2512.03262](https://arxiv.org/abs/2512.03262).
- [Temporal Reasoning over Evolving Knowledge Graphs (arXiv 2509.15464)](https://arxiv.org/html/2509.15464v1).
- [Karpathy LLM knowledge-base gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Models

- **Ollama cloud** (context windows): deepseek-v4-pro/flash:cloud (1M), kimi-k2.6:cloud (256K), glm-5.1:cloud (198K), devstral-2:123b-cloud (256K), qwen3.5:cloud / qwen3.5:397b-cloud (256K), nemotron-3-super:cloud (256K), minimax-m2.7:cloud (200K).
- **HuggingFace**: [supergemma4-26b-uncensored-gguf-v2](https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-gguf-v2), [openai/privacy-filter](https://huggingface.co/openai/privacy-filter), [Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B).

## Official docs

- **Claude Code**: [agents](https://code.claude.com/docs/en/agents), [sub-agents](https://code.claude.com/docs/en/sub-agents), [skills](https://code.claude.com/docs/en/skills), [hooks](https://code.claude.com/docs/en/hooks-guide), [MCP](https://code.claude.com/docs/en/mcp), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) - full 47-page set in ledger.
- **Google ADK**: [adk.dev](https://adk.dev/2.0/), [get-started/python](https://adk.dev/get-started/python/), [Gemini Enterprise ADK](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk), [python-genai](https://googleapis.github.io/python-genai/), [Gemini deep-research](https://ai.google.dev/gemini-api/docs/deep-research).
- **LangGraph**: [docs.langchain.com/oss/python/langgraph](https://docs.langchain.com/oss/python/langgraph/overview) - full 16-page set in ledger.
- **OpenAI**: [cookbook](https://developers.openai.com/cookbook), [temporal-agents-with-knowledge-graphs example](https://developers.openai.com/cookbook/examples/partners/temporal_agents_with_knowledge_graphs/temporal_agents).
- **Strands**: [AWS intro blog](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-an-open-source-ai-agents-sdk/).

## Adjacent tooling

- **Workflow / orchestration**: [Apache Airflow](https://airflow.apache.org/) + [Task SDK](https://airflow.apache.org/docs/task-sdk/stable/index.html) (full set in ledger).
- **Task management**: [Taskwarrior](https://taskwarrior.org/) + [docs](https://taskwarrior.org/docs/start/) - OSS, preferred. Motion ([help](https://www.usemotion.com/help), [API](https://docs.usemotion.com/), full 83-page set in ledger) - ⚠️ **closed-source, deprioritized / abandoned path; retained as UX inspiration only, not a recommended dependency.**
- **Diagramming**: [mermaid-js/mermaid](https://github.com/mermaid-js/mermaid).
- **Terminal / dev utilities**: [vercel-labs/wterm](https://github.com/vercel-labs/wterm), [dmtrKovalenko/fff.nvim](https://github.com/dmtrKovalenko/fff.nvim), [s0xDk/ghostty-blackhole](https://github.com/s0xDk/ghostty-blackhole), [tw93/Mole](https://github.com/tw93/Mole), [mvanhorn/cli-printing-press](https://github.com/mvanhorn/cli-printing-press).
- **Geospatial**: [gboeing/osmnx](https://github.com/gboeing/osmnx).
- **Voice**: [supertone-inc/supertonic](https://github.com/supertone-inc/supertonic), [kyutai-labs/pocket-tts](https://github.com/kyutai-labs/pocket-tts) (see Serving).
- **Meetings / transcription**: [Zackriya-Solutions/meetily](https://github.com/Zackriya-Solutions/meetily) - local-first meeting recorder (Tauri + whisper.cpp/Parakeet + Ollama, no cloud round-trip). MIT (~24k★, checked 2026-07-14). A finished product, not a building block - value is as a reference implementation of a fully-local transcription pipeline. ⚠️ Open-core: "Meetily PRO" is a separate closed codebase; the MIT repo is Community Edition only.

## YouTube tutorials

- [Claude Code + Ollama = Free AGI (Full Setup)](https://www.youtube.com/watch?v=Hbp0yrVS6nA)
- [Self-Evolving Claude Code Memory w/ Karpathy's LLM Knowledge Bases](https://www.youtube.com/watch?v=7huCP6RkcY4)
- [Mastering Claude Code in 30 minutes](https://www.youtube.com/watch?v=6eBSHbLKuN0)

## To-triage / unverified

Surfaced in the bundle but not yet confidently mapped to a current, described
project. Link only - no invented descriptions. The next refresh pass triages
them.

- [1st1/lat.md](https://github.com/1st1/lat.md)
- [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)
- [InsForge/InsForge](https://github.com/InsForge/InsForge)
- [Lum1104/Understand-Anything](https://github.com/Lum1104/Understand-Anything)
- [TableProApp/TablePro](https://github.com/TableProApp/TablePro)
- [airweave-ai/airweave](https://github.com/airweave-ai/airweave)
- [algorithmicsuperintelligence/optillm](https://github.com/algorithmicsuperintelligence/optillm)
- [chopratejas/headroom](https://github.com/chopratejas/headroom)
- [cloudflare/agentic-inbox](https://github.com/cloudflare/agentic-inbox)
- [deeplethe/forkd](https://github.com/deeplethe/forkd)
- [eugeniughelbur/obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain)
- [garrytan/gbrain](https://github.com/garrytan/gbrain)
- [graykode/abtop](https://github.com/graykode/abtop)
- [koala73/worldmonitor](https://github.com/koala73/worldmonitor)
- [kyegomez/OpenMythos](https://github.com/kyegomez/OpenMythos)
- [mitkox/ai-coding-factory](https://github.com/mitkox/ai-coding-factory)
- [multica-ai/multica](https://github.com/multica-ai/multica)
- [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core)
- [openai/symphony](https://github.com/openai/symphony)
- [paperclipai/paperclip](https://github.com/paperclipai/paperclip)
- [reconurge/flowsint](https://github.com/reconurge/flowsint)
- [refactoringhq/tolaria](https://github.com/refactoringhq/tolaria)
- [rohitg00/pro-workflow](https://github.com/rohitg00/pro-workflow)
- [rowboatlabs/rowboat](https://github.com/rowboatlabs/rowboat)
- [simplifaisoul/osiris](https://github.com/simplifaisoul/osiris)
- [strukto-ai/mirage](https://github.com/strukto-ai/mirage)
- [misc-links datasciencedojo / google agents-cli](https://google.github.io/agents-cli/)

---

*The exhaustive, alphabetized URL set (479) is in [`link-ledger.md`](link-ledger.md). Add nothing here without checking it first.*
