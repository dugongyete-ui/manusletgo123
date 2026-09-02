---
name: webdev-owner-notifications
description: Dzeck webdev fullstack (web-db-user) & mobile-app (Expo) projects — pushing alert notifications to the project owner.
---

## Owner Notifications

Implement a `notifyOwner({ title, content })` helper (`server/_core/notification.ts`) and a protected tRPC mutation at `trpc.system.notifyOwner` following this shape. Use it whenever backend logic needs to push an operational update to the Dzeck project owner—common triggers are new form submissions, survey feedback, or workflow results. The channel is whatever the owner configures in `.env` — an email (SMTP) or a webhook URL.

1. On the server, call `await notifyOwner({ title, content })` or reuse the provided `system.notifyOwner` mutation from jobs/webhooks (`trpc.system.notifyOwner.useMutation()` on the client).
2. Handle the boolean return (`true` on success, `false` if the upstream service is temporarily unavailable) to decide whether you need a fallback channel.

Keep this channel for owner-facing alerts; end-user messaging should flow through your app-specific systems.
