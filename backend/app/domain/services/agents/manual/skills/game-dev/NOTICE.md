# Attribution Notice

This skill (`game-dev`) is an adaptation of the **godogen** project by Alex Ermolov.

- Upstream project: https://github.com/htdt/godogen
- Upstream author / copyright holder: Alex Ermolov (Copyright 2026)
- Upstream license: MIT License (see `LICENSE.txt` in this directory for the full text)

## What was reused and what was changed

- `references/godogen-stages/*.md` contains godogen's original stage instructions (visual-target, decomposer, architecture, scaffold, asset-planner, asset-gen, rembg, task-execution, quirks, scene-generation, capture, and the skill overview), reproduced substantially verbatim from the upstream repository, with inline "DZECK OVERRIDE" notes added where this sandbox environment differs.
- `references/dzeck-adaptations.md`, `SKILL.md`, and `templates/GameCanvas.tsx` are Dzeck adaptations that change three aspects of godogen: the host shell (a self-scaffolded React project instead of a bare Vite scaffold), asset generation (the image_generate tool instead of the paid Gemini/Grok/Tripo3D CLIs), and delivery (a verified zip instead of temporary links).

## License compliance

The MIT License permits use, copying, modification, and redistribution, provided that the original copyright notice and permission notice are included in all copies or substantial portions of the software. This skill satisfies that condition by including the full upstream MIT license text and copyright notice in `LICENSE.txt` and this attribution in `NOTICE.md`.

"godogen" is referenced for attribution and interoperability purposes only; this skill is not affiliated with or endorsed by the upstream author.
