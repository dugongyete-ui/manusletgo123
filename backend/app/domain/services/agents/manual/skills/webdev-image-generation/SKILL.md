---
name: webdev-image-generation
description: Fullstack web app builds — AI image creation or editing via a server-side helper against a provider of the user's choice.
---

## Image Generation Integration

No internal ImageService exists here. Two honest lanes:
- **Build-time (preferred in this sandbox):** YOU generate art while building — hand-crafted SVG/CSS illustrations, or permissively licensed assets — and ship them as static files. Zero keys, zero cost, works in the delivered zip.
- **Runtime generation:** implement `generateImage()` in `server/_core/imageGeneration.ts` against a provider of the USER's choice (key in `.env`, server-side only), returning a stored URL via the storage helper. Keep the call shape below so providers stay swappable.

Example usage:
```ts
import { generateImage } from "./server/_core/imageGeneration.ts";

const { url: imageUrl } = await generateImage({
  prompt: "A serene landscape with mountains"
});
// For editing:
const { url: imageUrl } = await generateImage({
  prompt: "Add a rainbow to this landscape",
  originalImages: [{
    url: "https://example.com/original.jpg",
    mimeType: "image/jpeg"
  }]
});
```

### Selecting a model

`generateImage()` defaults to **GPT Image 2** (`MODEL_GPT_IMAGE_2`) at `medium` quality. Pass `model` and/or `quality` to override:

```ts
const { url: imageUrl } = await generateImage({
  prompt: "A neon cyberpunk city at night",
  model: "MODEL_GPT_IMAGE_2",
  quality: "high",
});
```

When selecting a different model, omit `quality` unless that model supports the value you want to send.

### Listing available models

```ts
import { listImageModels } from "./server/_core/imageGeneration.ts";

const { models } = await listImageModels();
// e.g. [{ model: "MODEL_GPT_IMAGE_2", id: "gpt-image-2" }, ...]
```

Feed a `model` value from this list into `generateImage({ model })`.

Tips
- Always call from server-side code (e.g., inside tRPC procedures) to avoid exposing API keys
- Image generation can take 5-20 seconds, implement proper loading states
- Implement proper error handling as image generation can fail
