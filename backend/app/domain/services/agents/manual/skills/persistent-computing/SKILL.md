---
name: persistent-computing
description: "MUST read when the user needs something BEYOND what this sandbox delivers: persistent services that outlive a session (automation scripts, game servers, self-hosted open-source apps), Docker, fixed IP, always-on background jobs, heavy compute, or a reusable environment across sessions. Guides the choice: sandbox build + zip delivery vs a real deployment (Replit Deployments, a VPS, or any host the user picks)."
---

*Note for this workspace:* the `references/` files mentioned below are not shipped here — the decision framework in this document is self-sufficient for choosing build-here vs deploy-there.

# Persistent Computing

## When This Skill Applies

This sandbox (a Replit container or an E2B microVM) is EPHEMERAL task space: it exists to build and verify, then the deliverable ships as a zip. It does not host anything for the user. This skill helps you choose between "build here, deploy there" options for:

- **Always-on services**: websites/web apps, bots, game servers, VPN, monitoring
- **Self-hosted platforms**: WordPress, n8n, Gitea, Metabase, Dify, code-server
- **Docker or custom runtimes**
- **Scheduled/background jobs**: cron, parallel crawlers, task queues, data pipelines
- **Heavy or long-running compute**: large dataset processing, batch transcoding
- **Reusable environment**: pre-configured dev setup with databases, libraries, and local data that persists across sessions
- **Fixed IP**: webhook endpoints, DNS records, firewall allowlists

Most of these still start as a build here — including always-on bots, background workers, and long-running batch/ETL jobs behind a web UI: you build and verify the code in the sandbox, the user hosts it. The boundary for changing the approach is defined under Hosting Modes below.


## The Default Option: Build here, deliver as a zip

Build the project in this sandbox following the webdev skills, verify it runs, and deliver ONE structured zip. The user then runs or deploys it wherever they want:
- **Replit:** the user can import the project into their own Replit account — package.json scripts map directly (`npm install` → `npm run dev`), Replit Deployments give them an always-on URL with TLS
- **Any host (VPS, Render, Railway, Fly.io):** plain Node/Express + static build works everywhere; include a README with the exact run steps
- **Secrets stay in .env** on the user's side — never baked into the zip

Ship run instructions the user can actually follow (prereqs, install, start, verify) — that README is part of the deliverable.

**IMPORTANT:**
- External API integrations need the user's own credentials — wire the interface, put keys in `.env`, never bake them into the archive.
- Users may not explicitly ask for a "website" — requests to build a tool or workflow often want a GUI-based, low-barrier, universally accessible solution; that is still a build here.
- **Do not let an assumed implementation stack drive the platform choice.** Decide from the workload's hard requirements, then pick the stack.

### Hosting modes the user can pick after delivery

The zip you deliver runs in two shapes; both start from the same build:

| | Autoscale platform (e.g. Replit Deployments) | Reserved VM (VPS / always-on Repl) |
|---|---|---|
| **Process** | stateless, request-scoped | single persistent process, 24/7 |
| **Request timeout** | platform-capped | none |
| **Cold start** | yes, after inactivity | no |
| **Scaling** | auto-scales instances | single instance |
| **Cost** | usage-based | flat monthly |

A persistent process (WebSocket/realtime game server, bot, background
worker) wants the reserved shape — a single instance holding state.
Autoscale works when state lives in the database. OS-level control (root,
Docker, custom packages) or heavy resources = a real VM. Put this guidance
in the project README so the user can choose with the tradeoffs visible.

## Options beyond build-and-ship

### Option A: A small cloud VM (persistent server)

A plain Linux VPS from any provider the user likes (Hetzner, DigitalOcean,
Linode, Oracle free tier…). State and installed software survive forever;
the user owns it completely.

**Best for:** OS-level control — root, Docker, custom system packages,
fixed firewall — or resources a shared host cannot give.

**Capabilities:** full root, any software, Docker, fixed external IP,
persistent filesystem, cron, systemd. Ubuntu Server LTS is the common
default.

**Environment configuration:** ship an `AGENTS.md`/`README.md` with
environment, directory structure, and setup instructions — any future
agent (or human) working on that server reads it first, so the next
session does not re-derive what you already know.

**Cost note:** always mention the monthly cost range so the user can
decide — and mention the free alternatives (their own machine, free-tier
platforms) first.

### Option B: The user's own machine (run it locally)

Zero cost: `npm install && npm start` on their laptop. State persists on
their disk. Limits: uptime and network quality depend on the machine —
fine for personal tools, wrong for anything that must stay reachable.
The README's run instructions make this path one copy-paste.

### Option C: Third-Party Cloud Services

For advanced users with existing cloud accounts or production-grade needs, third-party cloud services are also a viable option.

## Decision Logic

Build-here + zip delivery is the default — prefer it whenever the
requirement is a working app the user can run. Persistence, background
work, or WebSockets are deployment concerns, not build concerns: ship
them correctly in the code and let the hosting choice carry them.

1. **Just needs a working app the user can run/deploy?** → build here,
   deliver the zip, write honest run instructions
2. **Persistent compute + user has a local machine?** → Option B as the
   zero-cost path
3. **Persistent server independent of the user's machine?** → Option A
   (mention the cost; free alternatives first)
4. **Advanced user with platform preferences?** → Option C

Never push a paid solution without explaining free alternatives first.
Objectively evaluate the workload on its merits.

## When the build outgrows this sandbox

If a build hits a genuine limit (Docker, non-Node runtimes, OS-level
control, heavy compute):

1. Explain what specifically cannot run in this sandbox — name the exact
   requirement, not a vague "it won't work".
2. Present the options above; say plainly that the project is portable
   (plain Node + static files) and the move is a deploy, not a rewrite.
