# Dzeck Adaptations Layer

This file defines exactly how godogen's canonical pipeline runs inside the
Dzeck sandbox. Read it together with `references/godogen-stages/*` (the
unmodified godogen stage instructions). Where this file conflicts with a
godogen stage file, this file wins — because it adapts godogen to this
sandbox (Replit / E2B) environment.

Layering principle: **React = picture frame, Babylon = canvas, godogen game code = the painting.**

---

## 1. Host shell: a self-scaffolded React project instead of godogen's Vite scaffold

godogen ships its own minimal Vite + `index.html` + `main.ts`. Do NOT use it as
the deliverable host. Instead:

1. Scaffold a `web-static` React + Vite + Tailwind project per the `webdev-readme-static` skill, inside `<home>/project/<game-name>/`.
2. Add Babylon to the project: `npm install @babylonjs/core` (and `@babylonjs/loaders` only if loading GLB models). Start the dev server with `npm run dev` as a long-running shell session and keep it running.
3. Create `client/src/components/GameCanvas.tsx` from `templates/GameCanvas.tsx`.
4. Render `<GameCanvas />` as the ONLY content of the `/` route in `client/src/App.tsx` (remove the demo Home page chrome). The game is full-screen.
5. Put all gameplay in `client/src/game/**` as plain TS classes — zero React coupling. This is where godogen's framework-agnostic modules (GameWorld, Player, ObstacleManager, etc.) live, ported almost verbatim.

### Babylon-in-React safety contract (non-negotiable)
- Initialize the `Engine` exactly once. Guard React 19 StrictMode double-mount with a ref flag (see template).
- `engine.dispose()` on unmount; remove every event listener you added.
- Render loop tied to component lifecycle (`engine.runRenderLoop` started after the scene resolves, stopped via dispose).
- Handle `window.resize` → `engine.resize()`.
- Attach input listeners to the canvas/window and clean them up on unmount.
- `client/src/game/scene.ts` must export `createGameScene(engine, canvas): Promise<GameHandle>` and a `GameHandle` type with `{ scene, dispose() }`.

### Import paths
Import Babylon from deep paths to keep bundles lean, e.g.
`import { Engine } from "@babylonjs/core/Engines/engine";`
`import { Scene } from "@babylonjs/core/scene";`
Use side-effect imports for features actually used (e.g. `@babylonjs/core/Materials/standardMaterial`).

---

## 2. Art step: the image_generate tool (MANDATORY — never skip)

godogen's `asset-planner.md` / `asset-gen.md` call paid Gemini / xAI Grok /
Tripo3D CLIs. Here those are REPLACED by the `image_generate` tool. The
art step is mandatory: every game gets real generated art direction, never a
silent "no art" fallback.

Workflow:
1. **visual-target stage** → call `image_generate` and produce a reference image that defines art direction (palette, mood, perspective, density). Record it in `ASSETS.md`. (Read the `imagegen` skill for prompt structure.)
2. **asset-gen stage** → for each asset in the plan (sprites, textures, tiles, props, backgrounds, character art, UI art), generate an image with `image_generate`. For transparency, prompt for a clean transparent/cutout background (replaces godogen's rembg step).
3. **Wire assets into the game**:
   - Save each generated PNG into `client/public/assets/game/`.
   - Reference that path directly as a Babylon texture (`new Texture("/assets/game/xxx.png", scene)`), sprite, or skybox. Compress oversized images (target total media under a few MB) — the zip archive is the deliverable, so assets travel inside the project (see webdev-readme-static's media rules).
4. **3D models (GLB)**: this sandbox has no image→3D generation equivalent to Tripo3D. Default to **procedural meshes textured with generated images** (boxes/planes/extrusions + generated textures). Only if photoreal 3D models are essential, ask the user to provide a Tripo3D key and then follow godogen's `asset-gen.md` GLB path.

Budget note: godogen gates asset generation behind a "budget". Here, treat
the art step as always-on (image_generate), so generate a sensible, small
asset set by default; scale up only if the user asks.

---

## 3. Verification: browser + Playwright instead of capture.mjs

godogen's `capture.md` uses `scripts/capture.mjs` (Playwright) + a temporary
server. Here:
- Open the dev-server URL with `browser_navigate` and verify the game visually; take a Playwright screenshot for the record (`webapp-testing` skill). This honors godogen's core law: **trust the picture, not the code; if a requirement is not visible, it is unfinished.**
- For an autoplay/demo verification, add a `?demo` flag that drives a deterministic AutoPilot (port godogen's demo brain) so screenshots show real gameplay without manual input.
- Type-check with `npx tsc --noEmit` (or the project's check script). Inspect the dev-server shell session via `shell_view` (grep/tail) for runtime errors rather than reading whole files.
- godogen's GPU/software-renderer warning logic does not apply; the sandbox browser's rendering is sufficient for verification.

---

## 4. Delivery: a verified zip ONLY (raw dev-server URLs forbidden)

This is a hard rule. The final game is delivered as a zip archive:
1. Kill the dev server (`shell_kill_process`) once the game is verified.
2. Zip the project per the `packaging-delivery` skill and hand it off.
3. NEVER hand off a raw dev-server URL or any temporary link as the deliverable — this sandbox is ephemeral task space and the URL dies with the session. A dev-server URL is acceptable only for transient internal debugging, never as the handoff.

---

## 5. Context files (keep godogen fidelity)

Keep these inside the project root so the pipeline is resumable and faithful:
- `PLAN.md` — tasks + verification criteria + risk slices.
- `STRUCTURE.md` — architecture reference.
- `MEMORY.md` — discoveries, quirks, what worked/failed.
- `ASSETS.md` — generated-asset manifest with prompts + `/assets/game/...` paths.

On resume: if `PLAN.md` exists, read PLAN/STRUCTURE/MEMORY/ASSETS and skip to task execution (same as godogen).
