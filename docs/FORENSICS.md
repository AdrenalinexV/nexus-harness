# Forensic read of the engines already on this machine

> Congelado en `5e83a9a`: las cifras de este documento retratan ese árbol, no el de hoy.

Read-only inspection, 2026-10-24. Three sources: the active Hermes installation
(`%LOCALAPPDATA%\hermes\hermes-agent`), `aider` as installed in the Python 3.11 site-packages, and
the Nexus Protocol repository that governs this one. Every claim below names the file that carries it,
so a reader can check it without trusting this document.

## 1. hermes-agent — what a mature turn actually is

Size: 384 Python modules in `agent/`, ~17 MB. The interesting part is not its size, it is where it
draws the seams. Five seams matter for us.

| Seam | Evidence | What we take |
|---|---|---|
| Turn loop separated from the agent object | `agent/conversation_loop.py` docstring: *"drives one user turn (model call, tool dispatch, retries, fallbacks, compression, post-turn hooks)"* | Our `triad_loop` is a function over a `Run`, not a god-object. |
| Provider registry: name → provider, plus scoped maps | `agent/provider_registry.py`: `ProviderRegistry` with global map, per-profile scoped maps, a lock, register/snapshot/restore | One `Router` with a dict and role resolution; no plugin machinery because we have three transports. |
| Tool dispatch by name with resolvers | `agent/inline_tool_executors.py`: `resolve_invoke_tool_executor`, `InlineToolExecutor`, `_call_tool(module, func, args, arg_specs)` | Tool = name + JSON schema + one callable, all in `toolbox/registry`. |
| Compression is its own subtree, not a branch | `agent/context_compressor*.py` — 7 modules: prellm, prune, retry, summary, tail, telemetry | Context pressure is a measured number, not a guess: our `BudgetMeter`. |
| Sessions persist as first-class rows | `agent/runtime_session_store.py`, `runtime_session_lifecycle.py`, `session_persistence.py` | `session_store.py`: a session is a JSON file, so a relay is a file copy, not an anecdote. |

Rejected on purpose: the fallback/retry/entitlement/billing surface (`_billing_failure_result`,
`_nous_entitlement_message`, …). It exists because Hermes sells subscriptions; we run against
endpoints somebody already paid for. Copying it would be cargo cult.

Also rejected: the 400-line law is violated in the source (e.g. `conversation_loop.py` is >2000
lines). That is the one rule we do not inherit.

## 2. Aider — the edit format is the product

Aider's real invention is not the LLM call, it is the **deterministic edit protocol**:

* `aider/coders/search_replace.py` — `RelativeIndenter` normalises shared leading whitespace before
  searching, so a block that is indented differently from the file still matches.
* `aider/coders/editblock_coder.py` — `find_original_update_blocks()` parses `<<<<<<< SEARCH /
  ======= / >>>>>>> REPLACE` fences; `apply_edits()` locates the search chunk, and where an exact
  match fails it falls back to `SequenceMatcher(...).ratio()` against a `similarity_thresh = 0.8`,
  refusing below that instead of guessing.
* `aider/repomap.py` — `get_ranked_tags()` ranks definitions by how often the rest of the repo
  references them, so the map is a graph, not a directory listing.

What we take: exact-match-first, whitespace-normalised search, and **refusal below a similarity
floor** — a patch that is 60 % right is a corrupted file. What we refuse: the 0.8 fuzzy auto-apply
when several chunks tie. Our `toolbox/edit.py` applies exact matches only, and reports ambiguity as an
error with the candidate lines, because a wrong edit costs more than a retry.

What we take from `repomap`: the *ranking idea*, not the tree-sitter machinery. Skills routing already
scores against the files a turn touched; a second ranking system would fight it.

## 3. OpenCode — the shape of the interface

OpenCode is not installed on this machine (no `opencode` on PATH, nothing in
`%APPDATA%\npm\node_modules`). What we inherit from it is architectural, from its published design:
a **local server plus a thin client**, sessions as server-side resources, and one provider
abstraction covering local and hosted models. `ui.py` is exactly that: `http.server` serving a
single cockpit page and a JSON API, with the CLI as the second client of the same core. No
statement in this document claims to be measured from its source, because there is none here.

## 4. Nexus Protocol — the engine we fuse, not wrap

| Module | Interface we call | Why it is not reimplemented |
|---|---|---|
| `nexus/skills/routing.py` | `shortlist(files, limit=2)`, `brief(entries, lang)` | The prefilter is arithmetic over globs with a name-based tie-break; a second copy would drift. |
| `nexus/checks/rules_lint.py` | `lint_repo(root)` → `{findings, counts, files_scanned}` | R0–R3 are the law. Calling `main()` would lint NexusProtocol (its `ROOT` is fixed); `lint_repo(root)` takes a root. |
| `nexus/hive/relay.py` | `plan`, `checkpoint`, `budget`, `write_prompt` | A phase closes with observed exit codes; `checkpoint()` refuses evidence without one. |
| `nexus/hive/queue.py` | `load(root)` → open items | The mobile `/task` bridge is a read of the queue the protocol already writes. |

The consequence, and the whole point of this project: in Hermes, Claude Code or Cursor the protocol
has to act from outside through hooks or a `.nexus/skills-dormant/` shuffle. Here the routing, the
lint and the relay are **inside** the turn loop. There is no boundary to police because there is no
boundary.

## 5. What this means for the architecture

1. A turn is data (`Run`) driven by a function (`triad_loop.run`) — Hermes' seam, without the
   subscription surface.
2. Edits are deterministic and refuse ambiguity — Aider's floor, without the fuzzy tie-break.
3. The client is a browser page over a local server — OpenCode's shape, in 300 lines of stdlib.
4. Governance is imported, not re-described — Nexus' arithmetic, one definition per rule.
