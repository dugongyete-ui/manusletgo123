---
name: persistent-computing
description: "MUST read when the user needs to run persistent services that this build-and-zip sandbox cannot host (automation scripts, game servers, self-hosted open-source apps), or requires Docker, fixed IP, background jobs, heavy compute, or a reusable environment across sessions. MUST also read before recommending any deployment on a persistent VM (Replit Deployment / VPS / Cloud Computer). Guides build-here vs deploy-there."
---

# Persistent Computing

## When This Skill Applies

This sandbox (a Replit container or an E2B microVM) is ephemeral task space: it exists to build and verify, then the deliverable ships as a zip — it does not host anything for the user. This skill helps you choose between **building here** and the user's deployment options for:

- **Always-on services**: websites/web apps, bots, game servers, VPN, monitoring
- **Self-hosted platforms**: WordPress, n8n, Gitea, Metabase, Dify, code-server
- **Docker or custom runtimes**
- **Scheduled/background jobs**: cron, parallel crawlers, task queues, data pipelines
- **Heavy or long-running compute**: large dataset processing, batch transcoding
- **Reusable environment**: pre-configured dev setup with databases, libraries, and local data that persists across sessions
- **Fixed IP**: webhook endpoints, DNS records, firewall allowlists

Most of these still start as a build here (the default option) — including always-on bots, background workers, and long-running batch/ETL jobs behind a web UI: you build and verify the code, the user hosts it. The boundary for changing the approach is defined under Hosting Modes below.


## The Default Option: Build Here, Deliver a Zip

Build the project in this sandbox following the webdev skills (Vite + React + TypeScript + TailwindCSS, optional backend with TypeScript + Express + tRPC + Drizzle/SQLite), verify it runs, and deliver ONE structured zip. The user then runs or deploys it wherever they want:
- **Replit:** import the project into their own Replit account — package.json scripts map directly (`npm install` then `npm run dev`); Replit Deployments give an always-on URL with TLS
- **Any host (VPS, Render, Railway, Fly.io):** plain Node/Express + a static build works everywhere — include a README with the exact run steps
- **Secrets stay in `.env`** on the user's side — never baked into the zip, never exposed to the client

**Limitation:** A zip is portable but you are not the operator — once delivered, the app runs on the user's chosen host, not here. Ship run instructions the user can actually follow (prereqs, install, start, verify); that README is part of the deliverable.

**IMPORTANT:**
- If the user's project requires connectors: external API integrations need the user's own credentials — wire the interface, put keys in `.env`, never bake them into the archive.
- Users may not explicitly ask for a "website" — requests to build a tool or workflow often want a GUI-based, low-barrier, universally accessible solution; that is still a build here.
- **Do not let an assumed implementation stack drive the platform choice.** Decide from the workload's hard requirements (does it *need* a runtime/package/OS capability a zip cannot deliver?), then pick the stack.

### Hosting Modes

The delivered app runs in two shapes; both start from the same build (switching is a redeploy, not a rewrite) and share the same 1 vCPU / 512 MB entry-tier ceiling.

| | Autoscale platform (Replit Deployments, default) | Reserved VM (VPS / always-on) |
|---|---|---|
| **Process** | stateless, request-scoped | single persistent process, 24/7 |
| **Request timeout** | 15 min (cron included) | none |
| **Cold start** | yes, after inactivity | no |
| **Scaling** | auto-scales up to 5 pods | single reserved instance |
| **Cost** | usage-based, cheaper | fixed monthly, predictable |

Reserved is a single server process that runs continuously behind its HTTPS URL — functionally what you'd otherwise run on a VM. So needing a persistent process (a WebSocket/realtime game server, bot, or background worker) is **not** a reason to hand the user a raw VM — an always-on deployment is exactly what Reserved is for. (Nuance vs. Autoscale: Autoscale runs multiple instances, so a game holding room state *in memory* wants Reserved's single instance; if state is in the DB, Autoscale works too.) Go to a raw VM only for OS-level control (root, Docker, custom packages) or resources beyond the entry tier.

**IMPORTANT:** check the user's actual hosting budget before recommending Reserved Hosting or quoting its cost — free tiers sleep, always-on costs money.

## Beyond the Sandbox Build

### Option A: Persistent VM (VPS / Cloud Computer)

A persistent Ubuntu Server VM the user rents (Hetzner, DigitalOcean, AWS — or Replit Deployments' reserved instance). State and installed software survive across sessions; the user gets root.

**Best for:** OS-level control — root, Docker, custom system packages, fixed firewall — or resources beyond an entry-tier deployment.

**Capabilities:** full root, any software, Docker, fixed external IP, persistent filesystem, cron, systemd. Ubuntu Server 24.04 LTS, no desktop by default (can be installed manually). No GPU on any tier.

**Pricing:** small VPS instances start around $5–10/month.

**Environment configuration:** ship an `AGENTS.md`/README at the project root on that VM — any future operator (human or agent) working there reads it and gets the configuration, directory structure, and environment information without repeating setup instructions.

**IMPORTANT:** before recommending a VM purchase, check the provider's current tiers and operational rules (firewall/UFW, auto-restart, traffic limits) so the service actually stays up. Do not guess prices or specs from memory.

Answer product-level questions about hosting options inline with honest trade-offs; only hand the user to a provider's support for billing, refunds, or account issues.

### Option B: The User's Own Machine (Run the Zip Locally)

The user downloads the zip, extracts it, and runs it locally — zero hosting cost, full control. Node.js 20+ and npm are the only prerequisites; the README in the zip carries the exact steps (`npm install`, `.env` setup, `npm run dev`).

**Best for:** zero extra cost, leveraging existing hardware/data, data-sensitive scenarios

**Limitations:** machine must be online for the app to serve anyone; no public URL unless the user tunnels (cloudflared, ngrok); future edits by an agent require re-uploading the project

**User action:** download the delivered zip, extract, `npm install`, copy `.env.example` to `.env`, fill keys, `npm run dev`

### Option C: Third-Party Cloud Services

For advanced users with existing cloud accounts or production-grade needs, third-party cloud services are also a viable option.

## Decision Logic

Building here is the default — prefer it whenever it can satisfy the requirement. Persistence, background work, or WebSockets are not by themselves reasons to change the approach; an always-on deployment covers those, and you pick another option only after identifying a concrete limit of the build-and-zip flow.

1. **Anything a zip + a host can support when user has no special request on deployment target** → build here, deliver the zip (the user's Replit or any host covers persistent processes)
2. **Persistent compute + user has a local machine?** → Option B as zero-cost path (they run it themselves)
3. **Persistent server independent of the user's machine and beyond an entry-tier deployment?** → Option A
4. **Advanced user with platform preferences?** → Option C

When recommending Option A, always mention the cost so the user can make an informed decision. Never push a paid solution without explaining free alternatives first. On the flip side, a server the user already owns is strictly NOT a reason to skip the build-here flow — objectively evaluate the workload on its merits.

## Migrating beyond the zip

If a delivered project hits a genuine limit (Docker, non-Node runtimes, OS-level control, or resources beyond the entry tier):

1. Explain what specifically cannot be done within WebDev
2. Present the options above and tell the user there will be a migration process (re-deploy the same build on the new host; the README's run steps travel with it)
