---
name: webdev-file-storage
description: Fullstack web app builds — uploading and serving user files, images, documents via a storage helper (local disk in this sandbox; S3-shaped interface for later production).
---

## ☁️ File Storage

No storage service is injected here — implement `server/storage.ts` yourself with the SAME interface (storagePut / storageDelete), backed by local disk in this sandbox: files land in `data/uploads/<key>` and are served by one Express static route at `/uploads/`. The S3-shaped interface means swapping in real object storage later (Replit Blob, S3, R2) is a one-file change, not a refactor.

```ts
import { storagePut } from "./server/storage";

import { mkdir, writeFile } from "fs/promises";
import path from "path";

const UPLOAD_ROOT = path.resolve("data/uploads");

export async function storagePut(key: string, data: Buffer | Uint8Array | string, mime: string) {
  await mkdir(path.dirname(path.join(UPLOAD_ROOT, key)), { recursive: true });
  await writeFile(path.join(UPLOAD_ROOT, key), data);
  return { key, url: `/uploads/${key}` }; // served by the static route
}
// url = "/uploads/{key}" — use directly in frontend code
// key = unique storage key — save in database
```

Tips
- Save the `key` or `url` in your database; use storage for the actual file bytes. This applies to all files including images, documents, and media.
- For file uploads, have the client POST to your server, then call `storagePut` from your backend.
- Register the serving route once: `app.use("/uploads", express.static(UPLOAD_ROOT))` BEFORE the Vite/static fallthrough — `/uploads/...` is not auto-registered.
- To delete, implement `storageDelete(key)` (unlink the file) and call it when the DB row goes away — local disk does not garbage collect. Put `data/` under the app root; it is runtime state, so seed nothing there and keep it out of migrations.
