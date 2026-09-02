---
name: webdev-file-storage
description: Dzeck webdev fullstack (web-db-user) & mobile-app (Expo) projects — uploading and serving user files, images, documents via the built-in S3 storage helpers.
---

## ☁️ File Storage

Implement the storage helper in `server/storage.ts` following this shape — local disk under `data/uploads/` by default (the interface stays S3-shaped so a real bucket can drop in later). Files are stored with the app and served via the built-in `/uploads/` path — no manual URL management needed.

```ts
import { storagePut } from "./server/storage";

// Upload bytes to storage
const fileKey = `${userId}-files/${fileName}.png`
const { key, url } = await storagePut(
  fileKey,
  fileBuffer, // Buffer | Uint8Array | string
  "image/png"
);
// url = "/uploads/{key}" — use directly in frontend code
// key = unique storage key — save in database
```

Tips
- Save the `key` or `url` in your database; use storage for the actual file bytes. This applies to all files including images, documents, and media.
- For file uploads, have the client POST to your server, then call `storagePut` from your backend.
- The returned `url` (e.g. `/uploads/...`) is served by the Express static route — no manual URL management needed.
- To delete a file, drop its `key` from your DB and any UI references — the key is the only way to reach the object, so an unreferenced file is effectively gone. Do not implement a helper to remove the underlying object; the template's storage layer does not expose a delete endpoint.
