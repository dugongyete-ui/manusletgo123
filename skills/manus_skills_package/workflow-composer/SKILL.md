---
name: workflow-composer
description: "MANDATORY: Read this skill before planning or calling search, fetch, or agent whenever a task looks like a good fit for splitting into multiple subagent subtasks — typically researching, comparing, collecting, or analyzing 3 or more independent items, entities, topics, files, or records with similar output fields, each requiring independent research or judgment. Use `workflow/run` (the `run` tool on the `workflow` MCP server, called with the `mcp` tool using server: "workflow", name: "run") to compose those subtasks: one dedicated agent per item, structured results aggregated for you, instead of researching every item in the parent agent. NOT for parameter-only batches: running the same deterministic command or script over many inputs belongs in a single script with bounded concurrency, not in a workflow. Also use for loops, conditions, large fan-out, multi-stage map/reduce work, and deterministic subagent orchestration."
---

# Workflow Composer

`workflow/run` in this document means the `run` tool on the `workflow` MCP server: call it with the `mcp` tool using `server: "workflow"`, `name: "run"`.

`workflow/run` executes a deterministic JavaScript orchestration script that coordinates multiple subagents. The whole workflow runs as one background job; its return value is injected into the parent conversation when it finishes.

## When to use

Required condition — every item must clear this bar:

- Each item requires non-trivial independent reasoning, research, browsing, or open-ended tool exploration. Item count alone is never sufficient. Before reaching for `workflow/run`, ask: "could this be a single script looping over the items?" — if yes, write that script and execute it directly with bounded concurrency instead.

With that condition met, use `workflow/run` when any of the following applies:

- The task contains 3 or more independent, comparable items processable concurrently.
- The user asks to research, compare, summarize, or analyze many entities with the same output structure.
- The outputs need to be collected into a table, report, ranking, dataset, or other combined deliverable.
- The orchestration needs loops, conditions, retries, staged execution, aggregation, or a large/dynamic fan-out.

Do **not** use it when there are only 1–2 small independent tasks (direct `agent` calls are fine), when the items are answerable immediately from context, when the task is inherently sequential or tightly coupled, or when the per-item work is the same deterministic command or script with different parameters — that is a batch job for one script with bounded concurrency, not a workflow. For 3+ items that each need independent research or judgment, prefer `workflow/run`.

## Decomposition contract

For item-based fan-out:

1. Exactly one dedicated `agent()` call per independent item — never bundle several items into one subagent.
2. The parent agent must not perform item-level research before or alongside the workflow; it orchestrates.
3. Every subagent gets one clearly bounded subject and a fully self-contained prompt.
4. Comparable subagents share the same structured output fields (group `{schema}`).
5. Item agents run inside one named `parallel` group, preserving input order so outputs map back to inputs.
6. Handle individual failures without discarding successful results.

Bad: `agent('Research Nintendo, PlayStation, Xbox, Atari, Sega, …', {brief: 'Research all consoles'})`

Bad: `agent('run enrich.sh item-42')` × 230 — deterministic command fan-out belongs in a single script with bounded concurrency, not in per-item subagents.

Correct:

```javascript
const consoles = ['Nintendo NES', 'PlayStation', 'Xbox', 'Atari 2600', 'Sega Dreamcast']
const results = await parallel('Research consoles', () =>
  consoles.map(name =>
    agent(`Research ${name} and return the requested structured information.`, {brief: `Research ${name}`})
  )
)
```

## Map/reduce contract

When the final deliverable requires cross-item synthesis (comparative report, ranking, merged document, executive summary):

1. Map: one agent per item inside a `parallel` group.
2. Collect: keep successful structured results, record failures.
3. Reduce: exactly one reducer agent over the collected results.
4. Return: reducer output plus useful map results and files.

Count the reducer in both `estimated_agent_calls` and `max_agent_calls`. If deterministic code can combine the results without judgment (joining strings, returning rows), skip the reducer agent.

## Discovering the item set

- Items given by the user → use that list directly.
- Item set scopable from stable domain knowledge → define a reasonable list and state the selection criteria.
- Discovery itself requires research → run one discovery agent with a JSON Schema, read the array from its structured result, then fan out one agent per discovered item. Use a conservative high-side `estimated_agent_calls` and count the discovery agent (and any reducer) in the budgets.

## Execution model

- The script runs in a sandboxed JavaScript environment with **no I/O**: no filesystem, network, timers, or `require`/`import`. Subagents use their own tools and filesystem.
- The script **must be deterministic**: `Math.random()` and the entire `Date` object (including `new Date(...)` with arguments) are unavailable. Workflows survive restarts by replaying the script against a journal of completed `agent` calls; nondeterministic control flow breaks replay. Vary prompts by stable inputs or array indexes.
- Plain JavaScript control flow (variables, loops, conditionals, array methods, async/await, string/JSON operations) is fully available; the script body may use `await` directly.
- The script's completion value (`return` or last expression) becomes the workflow result.
- Workflow completion is a barrier over every `agent()` call: even if a Promise is not explicitly awaited, the job waits for that subagent to finish. Still use `await` or `parallel()` whenever its result participates in the returned value; an unawaited result is discarded.
- `script` must contain only a syntactically valid JavaScript function body — no Markdown fences or surrounding prose.

## Primitives

- `agent(prompt, {brief, schema, input_files, sandbox, effort_level})` returns a Promise of one subagent result. `brief` is **required** (≤120 chars): a self-explanatory title of what THIS subtask does, written in the user's language and specific to the item — shown verbatim as the subtask's row title in the user-facing task board. Say what is being done to what (e.g. `Scrape ACME pricing page`); never a generic label like `agent 3` / `subtask` / `Product 3`. Prompts must be self-contained (exact item, goal, required fields, source/verification requirements, constraints, expected file paths and output format): the subagent does not see the parent conversation.
- `parallel(brief, factory, {schema}?)` concurrently runs the agent promises returned by `factory` as a named group. `brief` is **required** (≤80 chars): a descriptive group name summarizing the whole batch, shown as the group header. `factory` must be a **function** returning an array of `agent()` promises — a bare promise array is rejected. Optional `{schema}` is the group default JSON Schema: agents created inside without their own `schema` inherit it; a per-agent `schema` overrides it; nested groups use the nearest enclosing schema.
- `log(message)` publishes concise progress, visible via `job` info.

## Structured results

Give every comparable-item group a shared JSON Schema: outputs stay structurally consistent, aggregation is reliable, and the UI renders the group as a table (columns from the schema's `properties`, one row per subagent result).

A successful `value` is already JSON-decoded when the subagent returned valid JSON — **never call `JSON.parse()` on a schema-constrained result**. Results are rejected unless they are valid JSON conforming to the effective schema (own `schema`, else nearest group `{schema}`).

## Files

- In a JSON Schema, `type: "file"` marks a field whose value is an absolute sandbox file path. File-typed paths in a subagent's result are promoted into that result's `files` (durable artifact refs) — this is the **only** way a subagent's output files enter the workflow result; a plain `type: "string"` path field is treated as text and its file is NOT captured.
- Declare every child input file explicitly in `input_files`: `{path: '/home/ubuntu/input.csv', name: 'data'}` for a parent-sandbox file, or pass ArtifactRef values from an earlier result (`input_files: previous.files`). A path merely mentioned in prompt text is never transferred.
- `sandbox: 'shared'` (default) runs subagents in the parent sandbox — give each item a deterministic, collision-free output path. `sandbox: 'isolated'` gives a fresh disposable sandbox for untrusted/heavy work; declared inputs are transferred and the child receives its actual local path.

## Budget parameters

- `effort_level`: default effort for every subagent in the workflow; defaults to `lite`. Each `agent()` may override it with `lite`, `standard`, or `max`. Keep independent research, extraction, and transformation on `lite`; use `standard` for reducers or complex judgment, and reserve `max` for exceptional cases.
  `effort_level` is only supported by the workflow input and each `agent()` options object; `parallel()` group options support only `schema`.

- `max_agent_calls`: hard upper bound on `agent()` calls (1–2000), not a credit limit. Put the full intended fan-out in one workflow rather than splitting it into trial batches.
- `estimated_agent_calls`: conservative high-side estimate of calls actually executed (≤ `max_agent_calls`). Count everything: discovery + item/map + reducer + validation agents. Exact count for deterministic lists; realistic high-side estimate for dynamic branches — never intentionally underestimate.

## Failure policy

Default and recommended for item fan-out: `collect`. Every `agent()` resolves to `{ok: true, value, files}` or `{ok: false, error}` in input order. `error` is `{code, message}` — read the fields; do not interpolate the whole object as a string. Preserve successful results even when some items fail:

```javascript
const successful = results.filter(r => r.ok).map(r => r.value)
const failures = results
  .map((r, i) => (r.ok ? null : {item: items[i], code: r.error.code, message: r.error.message}))
  .filter(Boolean)
```

Use `fail_fast` only when later work would be invalid after any individual failure.

## Confirmation gate

One confirmation check runs before any subagent starts: workflows estimated at ≤20 agent calls start automatically; larger ones return a pending job and show the user a confirmation card. A pending workflow is **already registered** — never call `workflow/run` again for the same task. Stop the turn and wait; on explicit acceptance use `job` to approve the exact job id, on explicit rejection use `job` to reject it. Never approve without a new user reply. Once approved, the workflow runs without another cost checkpoint.

## Recommended item-research template

```javascript
const items = [
  {id: 'item-a', name: 'Item A'},
  {id: 'item-b', name: 'Item B'},
  {id: 'item-c', name: 'Item C'}
]

const itemSchema = JSON.stringify({
  type: 'object',
  properties: {
    id: {type: 'string'},
    name: {type: 'string'},
    summary: {type: 'string'},
    key_facts: {type: 'array', items: {type: 'string'}},
    report_file: {type: 'file'}
  },
  required: ['id', 'name', 'summary', 'key_facts']
})

const mapped = await parallel(
  'Research all items',
  () => items.map((item, index) =>
    agent(
      'Research exactly one item: ' + item.name + '.\n' +
      'Verify important facts using authoritative sources.\n' +
      'Return the requested structured fields.\n' +
      'Write the detailed report to /home/ubuntu/reports/' +
      String(index + 1).padStart(2, '0') + '-' + item.id + '.md.',
      {brief: `Research ${item.name}`}
    )
  ),
  {schema: itemSchema}
)

const successful = mapped.filter(r => r.ok).map(r => r.value)
const failures = mapped
  .map((r, i) => (r.ok ? null : {item: items[i].name, code: r.error.code, message: r.error.message}))
  .filter(Boolean)

const reduced = await agent(
  'Create the final cross-item report using these structured results:\n' +
  JSON.stringify(successful) + '\n' +
  'Include a comparison table, key differences, shared patterns, and a clear conclusion. ' +
  'Save it to /home/ubuntu/reports/final-report.md.',
  {
    brief: 'Synthesize final report',
    schema: JSON.stringify({
      type: 'object',
      properties: {report: {type: 'file'}, summary: {type: 'string'}},
      required: ['summary']
    })
  }
)

return {items: successful, failures, final: reduced.ok ? reduced.value : null}
```

Budgets for this shape: `estimated_agent_calls = items.length + 1`, `max_agent_calls = items.length + 1`, `failure_policy = collect`.

## Final checklist

Before calling `workflow/run`, verify:

- The task genuinely contains multiple independent units of work — each needing independent research or judgment, not the same deterministic command with different parameters — with one agent per item and no bundling.
- Item prompts are self-contained; comparable agents share a JSON Schema; the group has a clear user-facing brief.
- File paths are deterministic and collision-free; output files use `type: "file"` fields; inputs are declared in `input_files`.
- Discovery and reducer agents are counted in the budgets; `collect` failures are handled explicitly.
- The script is valid deterministic JavaScript only.
- The parent agent is orchestrating, not doing item-level work itself.
