---
name: game-dev
description: "Build playable browser games (Babylon.js) end-to-end using the godogen production pipeline adapted to the Dzeck sandbox. Use when the user wants to make, generate, rebuild, or substantially extend a web/browser game from a natural-language brief. Runs godogen's staged workflow (visual target, risk decomposition, scaffold, architecture, asset generation, implementation, visual verification) but hosts the game in a Dzeck-built React project (webdev-readme-static), replaces godogen's paid art CLIs (Gemini/Grok/Tripo3D) with the image_generate tool, and delivers a verified zip instead of temporary links."
license: Complete terms in LICENSE.txt
---

# Game Dev

Build complete, playable Babylon.js browser games from a natural-language brief,
following the **godogen** production pipeline but running it natively inside the Dzeck sandbox.

This skill keeps godogen's engine (Babylon.js) and its disciplined workflow, while
adapting three things to this sandbox environment:
1. **Host shell** → a React + Vite + Tailwind project you scaffold yourself (not godogen's bare Vite scaffold).
2. **Art** → the **image_generate tool**, replacing godogen's paid Gemini/Grok/Tripo3D CLIs. The art step is **mandatory, never skipped**.
3. **Delivery** → a verified **zip** (packaging-delivery skill). Raw dev-server URLs are **forbidden** as the deliverable.

Layering principle to keep in mind throughout: **React = picture frame, Babylon = canvas, godogen game code = the painting.**

## Resources in this skill

- `references/dzeck-adaptations.md` — **read this first.** Exact rules for the project host, the image-generation art step, browser verification, and zip delivery. Overrides godogen stage files where they conflict.
- `references/godogen-stages/*.md` — the unmodified godogen stage instructions (`visual-target`, `decomposer`, `architecture`, `scaffold`, `asset-planner`, `asset-gen`, `rembg`, `task-execution`, `quirks`, `scene-generation`, `capture`, plus `godogen-skill-overview.md`). Read each stage file only when you reach that stage. Treat them as the source of truth for *how a good game is built*; apply the Dzeck adaptations for *where it runs and how art/deploy happen*.
- `templates/GameCanvas.tsx` — the Babylon-in-React integration component (single full-screen canvas, lifecycle-safe). Drop into the React project.

## Pipeline (godogen, adapted)

Follow these stages in order. On resume, if `PLAN.md` already exists in the project, read `PLAN.md`/`STRUCTURE.md`/`MEMORY.md`/`ASSETS.md` and skip to task execution.

1. **Set up the project host.** Scaffold the React + Vite + Tailwind project per the `webdev-readme-static` skill. `npm install @babylonjs/core` (add `@babylonjs/loaders` only for GLB). Start the dev server (`npm run dev`, long-running shell session). Add `GameCanvas.tsx` from the template and make `<GameCanvas />` the sole content of the `/` route. See `references/dzeck-adaptations.md` §1 for the non-negotiable canvas/React lifecycle contract.
2. **Visual target.** Read `references/godogen-stages/visual-target.md`. Call `image_generate` and produce a reference image defining art direction. Record it in `ASSETS.md`. (Art step is mandatory — see §2 of adaptations.)
3. **Decompose + risks.** Read `references/godogen-stages/decomposer.md`. Write `PLAN.md` with risk slices and verification criteria. Isolate high-risk features first (procedural generation/animation, sprite animation, vehicle physics, custom shaders, runtime geometry, dynamic navigation, complex cameras, pointer-lock, GLB import pipelines); everything else is main build.
4. **Architecture.** Read `references/godogen-stages/architecture.md`. Keep gameplay as plain TS classes under `client/src/game/` (GameWorld, Player, managers, etc.), framework-agnostic. Write `STRUCTURE.md`.
5. **Assets.** Read `references/godogen-stages/asset-planner.md` + `asset-gen.md` for *what* to plan, but generate with the `image_generate` tool (adaptations §2). Save generated PNGs into `client/public/assets/game/` and reference the `/assets/game/...` path as Babylon textures. Default to procedural meshes + generated textures; only use real GLB models if the user supplies a Tripo3D key. Maintain `ASSETS.md`.
6. **Implement.** Read `references/godogen-stages/task-execution.md`, `quirks.md`, and `scene-generation.md`. Build risk slices first, then the main build. Inner loop: edit `client/src/game/**` → HMR → screenshot → check.
7. **Verify (trust the picture).** Verify in the browser against the dev server (adaptations §3) — `browser_navigate` + a Playwright screenshot per the `webapp-testing` skill, not godogen's `capture.mjs`. Add a `?demo` deterministic AutoPilot so screenshots show real gameplay. Run the project's type-check (`npx tsc --noEmit` or its check script). If a requirement is not visible in a screenshot, it is unfinished. When code and picture disagree, trust the picture.
8. **Deliver.** Kill the dev server (`shell_kill_process`), then zip the project per the `packaging-delivery` skill (adaptations §4). NEVER hand off a raw dev-server URL.

## Non-negotiable rules

- **Art is mandatory and uses the image_generate tool.** Never silently skip art or ship only flat placeholder colors. Procedural geometry is fine, but art direction must come from a generated reference and generated textures/assets.
- **Delivery is always a verified zip.** Raw dev-server URLs are not an acceptable final deliverable.
- **Keep godogen context files** (`PLAN.md`, `STRUCTURE.md`, `MEMORY.md`, `ASSETS.md`) in the project root for fidelity and resumability.
- **Preserve godogen philosophy:** risk slices first, read stage files on demand, and verify visually.
- **Respect the Babylon-in-React contract** (init once, dispose on unmount, handle resize, guard StrictMode) — see template and adaptations §1.

## Quirks worth front-loading

- React 19 StrictMode mounts effects twice in dev → guard Babylon engine init with a ref flag, or you get two engines on one canvas.
- Keep generated image assets lean: compress oversized PNGs and keep total media under a few MB — the zip archive is the deliverable, so assets travel inside `client/public/assets/game/` (see webdev-readme-static's media rules).
- Import Babylon from deep module paths to keep the bundle small.
- Babylon needs a non-zero-size canvas; the full-screen `fixed inset-0` canvas in the template handles this. Call `engine.resize()` on window resize.
