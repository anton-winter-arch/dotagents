# Scaffolding a containerized project

Templates that already pass `scripts/docker_check.py`. Copy, then adapt - do not
retype from memory, that is how the root user and the cache-busting COPY come
back.

## Contents

- [Decide first](#decide-first)
- [Python (uv / pip)](#python-uv--pip)
- [Node (pnpm / npm)](#node-pnpm--npm)
- [Go (static, distroless)](#go-static-distroless)
- [.dockerignore](#dockerignore)
- [Compose: dev vs prod](#compose-dev-vs-prod)
- [Choosing a base image](#choosing-a-base-image)

## Decide first

Three questions, answered out loud, before any file exists:

1. **Build-time vs run-time.** What does compiling need that running does not?
   Everything in that gap belongs in a discarded stage.
2. **Dev loop vs shipped image.** Dev wants your source bind-mounted and a
   reloader. Prod wants the source baked in and no reloader. These are two
   different compose files, not one file with a flag.
3. **What must never enter the image.** Secrets, `.git`, test fixtures, the
   `.venv`. That answer is the `.dockerignore`, and writing it first is cheaper
   than discovering a leaked `.env` in a published layer.

## Python (uv / pip)

```dockerfile
# Pin a digest: a tag can be re-pointed under you.
FROM python:3.13-slim@sha256:<digest> AS build
WORKDIR /app

# Manifest first, install second, source last - this is the whole cache story.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.13-slim@sha256:<digest>
WORKDIR /app
COPY --from=build /install /usr/local
COPY src/ ./src/

RUN useradd --system --uid 10001 app
USER app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
HEALTHCHECK --interval=30s --timeout=3s \
  CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"]
CMD ["python", "-m", "src.main"]
```

With `uv` (faster, and the lockfile is the manifest):

```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
```

A build-time secret, done correctly - mounted, never layered:

```dockerfile
RUN --mount=type=secret,id=pip_token \
    PIP_INDEX_URL="https://$(cat /run/secrets/pip_token)@pypi.internal/simple" \
    pip install --no-cache-dir -r requirements.txt
# docker build --secret id=pip_token,src=./token.txt .
```

## Node (pnpm / npm)

```dockerfile
FROM node:22-slim@sha256:<digest> AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build && pnpm prune --prod

FROM node:22-slim@sha256:<digest>
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node                      # the node image already ships a non-root user
HEALTHCHECK --interval=30s CMD ["node", "-e", "fetch('http://localhost:3000/healthz').then(r=>process.exit(r.ok?0:1))"]
CMD ["node", "dist/main.js"]
```

## Go (static, distroless)

The best case: nothing in the final image but the binary.

```dockerfile
FROM golang:1.24@sha256:<digest> AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
USER nonroot:nonroot
ENTRYPOINT ["/app"]
```

No shell means no `docker exec` debugging. That is the trade: hostile to
attackers, hostile to you. Use the `:debug` variant when you need a shell.

## .dockerignore

Write this **first**. Everything not excluded is uploaded to the daemon and can
land in a layer.

```
.git
.env
.env.*
*.pem
*.key
__pycache__/
*.pyc
.venv/
node_modules/
dist/
.pytest_cache/
.mypy_cache/
**/*.md
Dockerfile*
docker-compose*
```

## Compose: dev vs prod

Dev - source mounted, reloader on, ports exposed to you only:

```yaml
# compose.dev.yml
services:
  api:
    build:
      context: .
      target: build          # stop at the fat stage; it has the dev tooling
    command: uvicorn src.main:app --reload --host 0.0.0.0
    volumes:
      - ./src:/app/src:ro    # read-only: the container should not edit your source
    env_file: .env           # gitignored, never COPYed
    ports:
      - "127.0.0.1:8000:8000"   # bind to loopback, not 0.0.0.0
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set it in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

volumes:
  pgdata:
```

Prod - nothing mounted, nothing reloaded, privileges dropped:

```yaml
# compose.prod.yml
services:
  api:
    image: registry.example.com/api:${TAG:?}
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp
    deploy:
      resources:
        limits:
          memory: 512M
```

Note what is **absent** from both: no `privileged`, no `network_mode: host`, no
`/var/run/docker.sock`, no `- /:/host`. If you are reaching for one of those,
stop and read the privilege section of SKILL.md.

## Choosing a base image

| Base | Use when | Cost |
|---|---|---|
| `-slim` | default for Python/Node | glibc, sane debugging, ~80MB |
| `alpine` | you need the smallest and control the deps | **musl** - breaks manylinux wheels, and Python can be measurably slower |
| `distroless` | production services, no shell wanted | no shell: no `exec` debugging (use `:debug` tag) |
| `scratch` | static Go/Rust binary | nothing at all, including CA certs and timezones |
| full (`python:3.13`) | build stage only | do not ship it |

Default to `-slim`. Reach for `alpine` only with a reason, and never reflexively
for Python - the musl wheel problem is real and costs more time than the
megabytes are worth.
