---
name: static-landing-page
description: "Landing pages, portfolios, promo pages, and other static sites: hand-crafted HTML/CSS/JS that looks designed, verified in the browser, delivered as one .zip."
---

# Static Landing Page

For pages whose job is to LOOK good and communicate: landing, promo,
portfolio, event page, product one-pager.

## Workflow
1. **Collect the content first** — real text beats lorem ipsum. If the task
   gives no copy, write real copy for the described product (2-3 variants of
   the headline), never filler.
2. **Plan sections before styling**: hero → value → features → proof → CTA
   (adapt to the request). Sketch the hierarchy in one line per section.
3. **Build the folder**: `index.html`, `styles.css`, `app.js`, `assets/`.
   One page = these 3-4 files. Multi-page = shared css/js, one file per page.
4. **Design rules that read as "designed"** (see DESIGN.md):
   - one accent color + neutrals; type scale (14/16/20/28/40+);
   - generous whitespace; consistent 8px rhythm;
   - mobile-responsive (flex/grid, media query at ~480px), tap targets
     ≥ 40px;
   - real images: `image_search_web` + `image_download` into `assets/`, or
     clean SVG/CSS shapes — never broken-image placeholders.
5. **Serve & see it**: `python3 -m http.server 8000` in the folder →
   `browser_navigate http://localhost:8000` → read the elements, screenshot,
   fix what looks off (spacing, overflow). At ~1280px AND a phone-ish
   viewport if you can.
6. **Console clean**: `browser_console_view` — no red errors.
7. **Kill server, zip, verify, deliver** (packaging-delivery skill).

## When NOT to use
Anything with a server, database, or API → fullstack-web-app.

## Gotchas
- Fonts from CDNs fail offline → system-ui stack as base, CDN font as
  progressive enhancement with fallback.
- Background images need `background-size: cover` and a text overlay layer
  for contrast — test with the screenshot, not imagination.
- Deliver loose `index.html + styles.css` files? No — 2+ files = zip (see
  DEPLOYMENT.md).
