---
name: webdev-owner-notifications
description: Fullstack web app builds — pushing operational alerts to the app owner (email or webhook), implemented server-side.
---

## Owner Notifications

There is no platform notifier here — implement `notifyOwner({ title, content })` in `server/_core/notification.ts` yourself, exposed as a protected tRPC mutation `trpc.system.notifyOwner`. Two channels, chosen by which env the user provides:
- **Webhook (simplest):** `OWNER_WEBHOOK_URL` → POST JSON `{title, content}` (works with Discord/Slack/Telegram bot endpoints via their webhook shapes)
- **Email:** `SMTP_HOST/PORT/USER/PASS` + `OWNER_EMAIL` via nodemailer
Use it whenever backend logic should push an operational update — new form submissions, survey feedback, workflow results.

1. On the server, call `await notifyOwner({ title, content })` or reuse the provided `system.notifyOwner` mutation from jobs/webhooks (`trpc.system.notifyOwner.useMutation()` on the client).
2. Return a boolean (`true` delivered, `false` when the channel is unconfigured or temporarily failing) and LOG the failure — the app owner must be able to see that alerts silently stopped.

Keep this channel for owner-facing alerts; end-user messaging should flow through your app-specific systems.
