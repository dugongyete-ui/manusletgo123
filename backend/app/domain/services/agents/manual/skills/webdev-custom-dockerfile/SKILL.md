---
name: webdev-custom-dockerfile
description: Write production-grade Dockerfiles and compose files for web projects. Use when the user asks to dockerize an app, ship a Dockerfile, or containerize a build for deployment — even though this sandbox itself has no Docker daemon.
---

# Custom Dockerfile for Web Projects

## When to Use

- The user asks to dockerize / containerize a web app or service
- A deployment target requires a container image
- The deliverable must be runnable on the user's own machine ("give me docker")

## Reality First

- The sandbox has **no Docker daemon** — you cannot `docker build` here. The
  deliverable is a correct, reviewed Dockerfile (+ compose file) with a
  README. Review by reading, not by building: lint the file logically,
  trace the paths, check every COPY source exists on disk.

## Recipe That Works (Python web service)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN addgroup --system app && adduser --system --ingroup app app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Quality Bar

- **Pin the base image tag** (`python:3.12-slim`, not `latest`).
- **Layer order**: dependencies (rarely changing) before source (always changing)
  — rebuilds stay fast.
- **Never run as root**: create a user, `USER app` before CMD.
- **`.dockerignore`**: node_modules, .venv, .git, __pycache__, .env — a leaked
  `.env` inside an image is a real secret leak.
- **Health check**: for compose, add a healthcheck hitting the app's /health.
- **One process per container**; no supervisor inside the image.

## Deliverable Checklist

- `Dockerfile` + `.dockerignore` + `docker-compose.yml` (when multi-service)
- README section: `docker build -t app .` / `docker run -p 8000:8000 ...`
  with env vars the user must set (from `.env.example`, never real secrets)
- A one-line honesty note in chat that the build was reviewed but executed
  on the user's host, since the sandbox cannot run Docker.
