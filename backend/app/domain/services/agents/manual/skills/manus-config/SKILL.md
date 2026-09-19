---
name: manus-config
description: Inspect and manage project runtime configuration with the manus-config registry tool. Use when the user asks to check project settings, change configuration values, or when a build needs to read config rather than guess it.
---

# Project Configuration (manus-config)

## When to Use

- Before a build that depends on configurable values (ports, flags, feature toggles)
- The user asks "what is configured?" or asks to change a setting
- A task failed for an environment reason and the actual config must be verified

## How It Works

- The sandbox exposes the **`manus-config`** registry tool for reading and
  writing project-level runtime configuration — prefer it over editing raw
  files when both are possible, because it validates values and records intent.
- For read-only checks a shell fallback exists (`env`, `printenv KEY`), but
  the tool is the source of truth for project settings.

## Working Rules

1. **Read before write.** Pull current values first; report what changes and
   why before applying anything destructive.
2. **Minimal diffs.** Change only the keys the task actually needs.
3. **Verify after write.** Re-read the key and show the new value in your
   progress output.
4. **Secrets are not config values.** API keys belong in environment variables
   set by the user — the config tool is for non-secret settings.

## Typical Flow

```
1. manus-config → list/read relevant keys
2. decide the minimal change set (say it in one line to the user)
3. apply via manus-config (or .env for local dev keys)
4. re-read → confirm → continue the build
```

## Anti-Patterns

- Guessing config values instead of reading them — the #1 cause of "works in
  one session, fails in another".
- Hardcoding what should be config: if a build hardcodes a port/URL/key, that
  is a defect to fix before delivery.
