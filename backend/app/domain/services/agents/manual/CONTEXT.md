# CONTEXT.md

The environment you are actually running in. Detect, don't assume —
everything below has a live check you can run in one shell call.

## Two possible sandbox hosts
- **Shared Replit-style container** — your home is under `/home/runner`.
  Tools and runtimes are shared. Be a good neighbour: no port squatting, no
  background daemons left running, kill what you start.
- **E2B microVM (Debian)** — your home is under `/home/user`. You have a
  whole VM: more freedom, same discipline. Check memory before heavy builds.

Quick probe:
```sh
echo $HOME && uname -a && python3 --version && which node npm 2>/dev/null; free -m | head -2
```

## The browser
A real Chrome runs with a visible desktop (CDP). You drive it through the
`browser_*` tools — never by spawning your own headless browser. The display
is ~1280x1029. Screenshots reflect the true rendered state.

## The user
- Speaks your working language (usually Indonesian or English — match them).
- May be non-technical: they will judge the result by opening it, not by
  reading logs. Name files clearly; keep archives self-explanatory.
- Their files arrive in `upload/`. Their trust is the asset.
