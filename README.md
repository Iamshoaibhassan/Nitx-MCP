# Nitx Poster MCP Server

An MCP server that lets an AI agent generate marketing posters through a poster-generation
service — plus a mock backend that stands in for that service, because the real one
(Nitx's) doesn't exist for this exercise. The mock isn't a toy: it behaves like a genuine
asynchronous API — jobs take 5–20 seconds, roughly one in ten fails at random, bad input
gets rejected before anything is created — and the whole system (backend, job queue,
workers) is built to survive a crashed process and scale past one machine, not just to
pass a demo.

If you only read one thing, read this: **the MCP server and the backend are two separate
processes that talk over plain HTTP, exactly like they would in production.** That one
decision shapes almost everything else in this repo, and it's worth understanding before
diving into the rest — see [Why two processes instead of one](#why-two-processes-instead-of-one).

## Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [The API](#the-api)
- [The MCP tools](#the-mcp-tools)
- [Idempotency](#idempotency)
- [The job queue and workers](#the-job-queue-and-workers)
- [Rate limiting and concurrency limits](#rate-limiting-and-concurrency-limits)
- [Error handling](#error-handling)
- [Scalability, honestly assessed](#scalability-honestly-assessed)
- [Getting started](#getting-started)
- [Running with Docker](#running-with-docker)
- [Tests](#tests)
- [A note on Redis on this dev machine](#a-note-on-redis-on-this-dev-machine)
- [Transcript](#transcript)
- [Written answers](#written-answers)

## Highlights

A few things in here that go beyond what the brief strictly asked for, because they're
the difference between "a mock that returns the right JSON" and something that would
actually survive contact with a real deployment:

- Job *creation* and job *execution* are different processes connected only through
  Redis — kill a worker mid-render and a different one finishes the job, proven by
  actually doing it (not just asserted).
- Idempotency works even if the caller never thinks about idempotency keys: identical
  requests are deduplicated automatically via a hash of their contents.
- Every error response tells the caller what to do next, not just that something went
  wrong, and the four-ish HTTP status codes in use (400/401/404/409/429) are each used
  for exactly one meaning, consistently.
- Rate limiting and a per-key concurrent-job cap are enforced in Redis, not just
  described as "what you'd add for production" — and there's a short, honest section on
  what's *still* not atomic about them.
- 33 tests, all running against a real Redis instance and a real worker loop — no mocked
  Redis client anywhere, after one bit us early on with a behavioral mismatch.

## Architecture

```
                         ┌───────────────┐
  AI Agent ── MCP ────►  │  MCP server   │   ── HTTP + X-API-Key ──►   ┌─────────────┐
                         │  (4 tools)    │                              │   FastAPI   │
                         └───────────────┘                              │   backend   │
                                                                         └──────┬──────┘
                                                                                │
                                                                                ▼
                                                                         ┌─────────────┐
                                                           ┌────────────▶│    Redis    │◀────────────┐
                                                           │             └─────────────┘              │
                                                 reads job,│      job hashes · job queue (Stream)       │
                                                 writes result   · idempotency keys · rate limits       │
                                                           │      · active-job sets                     │
                                                   ┌───────┴────────┐                                   │
                                                   │   Worker(s)    │───────────────────────────────────┘
                                                   │ (any number)   │        also reads/writes Redis
                                                   └────────────────┘
```

Three processes, each independently runnable, independently restartable, and (for the
backend and the worker) independently *scalable* — plus one shared source of truth.

**The backend** (`src/main.py`, run with `uvicorn`) is the front door. It owns auth,
input validation, and reading/writing job state. It does *not* render anything — when
you call `POST /jobs`, the backend writes a record to Redis, drops a pointer on a queue,
and returns in milliseconds. The actual 5–20 second wait happens somewhere else entirely.

**The worker** (`src/worker/poster_worker.py`) is that somewhere else. It's a small,
standalone process whose only job is to watch the queue, pick up pointers nobody else has
claimed, and do the (simulated) rendering. You can run one, or ten, on one machine or
several — they coordinate through Redis, never through shared memory, which is exactly
why more than one of them can exist at all.

**The MCP server** (`src/mcp_server/server.py`) is the only thing the AI agent ever
talks to. It exposes four tools and translates each one into an HTTP call against the
backend. It holds the API key, reads it from the environment, and never lets it leak into
a tool result or a log line.

### Why two processes instead of one

It would be simpler, on paper, for the MCP server to just import `JobService` and call
its methods directly — no HTTP, no serialization, no network. I deliberately didn't do
that, for three reasons that all matter more than the convenience:

1. **The backend is a stand-in for a service that doesn't run in this process, in this
   language, or on this machine.** Nitx's real API is the thing being mocked here. An MCP
   layer that imports Python classes from the mock would have to be *rewritten* the day
   the mock is swapped for the real thing. One that only knows an HTTP contract doesn't
   change at all.
2. **Auth only means something across a boundary.** `verify_api_key` and the rate limiter
   exist to protect a service from its callers. Collapse the MCP server and the backend
   into one process and there's no real boundary left to protect — the check becomes
   theater.
3. **The scaling story in this README depends on it.** The worker tier only works as an
   independently-scalable unit because nothing anywhere assumes job execution happens in
   the same process that accepted the HTTP request. If the MCP server called job logic
   directly, there'd be nothing left to put a queue in front of.

### Project layout

```
src/
  utils/         ENV-dict loader, structured JSON logging, the error-response builder
  config/        A Settings object built from that ENV dict — no defaults, no caching
  redis/         The Redis connection and all key-naming in one place
  auth/          API-key verification, the rate-limit dependency, caller-id hashing
  middleware/    Request logging
  models/        Every request/response shape and enum — the actual API contract
  exceptions/    One exception type per failure mode + the handlers that turn them into JSON
  services/      Job creation/cancellation and the template catalog
  controllers/   The FastAPI routers
  worker/        The Redis Streams queue and the process that consumes it
  mcp_server/    The four MCP tools, and the HTTP client they use to reach the backend
  main.py        Wires all of the above into one FastAPI app
```

Every folder exports its public names through its own `__init__.py`, so code reaching
*into* another package writes `from src.services import JobService`, never
`from src.services.job_service import JobService`. Inside a package, sibling files still
import each other directly — the shortcut is for crossing a boundary, not for every
import that exists. There's no empty top-level `src/__init__.py` either; `src` is a
plain namespace package, and only the subpackages that actually export something carry
one.

## The API

Every route except `/health` requires an `X-API-Key` header, checked with
`secrets.compare_digest` against the value from the environment.

| Method & path | What it does |
|---|---|
| `GET /health` | Liveness check. No auth. |
| `GET /templates` | Browse the template catalog, optionally filtered. |
| `POST /jobs` | Start a poster job. Returns immediately. |
| `GET /jobs/{job_id}` | Check a job's current status. |
| `POST /jobs/{job_id}/cancel` | Stop a job that's still running. |

### `GET /templates`

A fixed catalog of 10 templates, hard-coded in `template_service.py` — no database, no
pagination, because there's nothing here that needs one. `category` is an exact-match
filter on one of `event` / `product` / `sale` / `social` / `real_estate` / `restaurant`;
`search` is a case-insensitive substring match against the template name. Neither
parameter is required, and an unmatched filter returns an empty list, not an error.

```
GET /templates?category=sale
→ 200
{"templates": [
  {"id": "tpl-002", "name": "Holiday Sale Blast", "category": "sale"},
  {"id": "tpl-004", "name": "Flash Discount Flyer", "category": "sale"}
]}
```

### `POST /jobs`

This is where almost everything interesting in this project lives — idempotency, the
concurrency cap, and the handoff to the queue all happen here. The full walk-through is
in [Idempotency](#idempotency) and [The job queue and workers](#the-job-queue-and-workers)
below; the short version of what happens, in order:

1. Validate the body (`prompt` ≤ 500 chars, `image_count` 1–4, `resolution` is `1k` or
   `2k`) — anything else is `400` before any of the rest of this runs.
2. Resolve an idempotency key — either the one you sent, or one derived automatically by
   hashing the request — and check whether it's already been used. If it has, hand back
   the *original* job instead of creating a second one.
3. Check this API key isn't already at its concurrent-job limit.
4. Write the job's record to Redis (`status: processing`), add it to the caller's
   active-job set, and drop its id on the work queue.
5. Return `202 Accepted` with `{job_id, status: "processing"}` — before any rendering has
   happened at all.

```
POST /jobs
{"product_image": "...", "background_image": "...", "prompt": "Weekend sale, bold red text",
 "image_count": 2, "resolution": "2k"}
→ 202
{"job_id": "job-e592518725b845bc", "status": "processing"}
```

### `GET /jobs/{job_id}`

A pure read — `HGETALL` on the job's Redis record, nothing computed, nothing else
touched. This is what you poll every couple of seconds while `status` is `processing`.

```
GET /jobs/job-e592518725b845bc
→ 200   (while still rendering)
{"job_id": "job-e592...", "status": "processing", "images": null, "error": null, ...}

→ 200   (once finished)
{"job_id": "job-e592...", "status": "completed",
 "images": [{"id": "job-e592...-img-1", "url": "https://mock-cdn.nitx.ai/posters/job-e592.../1.png", "resolution": "2k"}, ...],
 "error": null, ...}
```

A `job_id` that was never issued, or whose record has aged past
`JOB_RECORD_TTL_SECONDS` (24 hours by default), returns `404` with a message saying so
rather than a bare status code.

### `POST /jobs/{job_id}/cancel`

Flips a still-`processing` job's status to `cancelled` and frees its slot in the
caller's concurrency count. It does **not** reach into the worker that might be rendering
that job right now — there's no mechanism for one process to reach into another's memory
here, by design. The worker notices on its own, within half a second (see
[The job queue and workers](#the-job-queue-and-workers)).

```
POST /jobs/job-e592518725b845bc/cancel
→ 200                                             → 409 (already finished)
{"job_id": "job-e592...", "status": "cancelled"}   {"error": {"code": "CONFLICT",
                                                      "message": "Job 'job-e592...' already
                                                      finished with status 'completed' and
                                                      cannot be cancelled. ..."}}
```

## The MCP tools

Four tools, one-to-one with the endpoints above, defined in `src/mcp_server/server.py`
using `mcp`'s `MCPServer` (the 2.x successor to `FastMCP`). Each parameter is annotated
with `pydantic.Field` constraints and a plain-English description — `image_count: ge=1,
le=4`, `prompt: max_length=500`, `resolution: Literal["1k", "2k"]` — which become the
JSON schema the LLM sees *before* it ever makes a call. An agent literally can't
construct `create_poster_job(image_count=7)`; the schema rules it out at the client side.

`list_templates`, `get_job_status`, and `cancel_job` are thin wrappers that just forward
to the matching endpoint and return its JSON. `create_poster_job`'s docstring explicitly
tells the model not to wait for a result and to poll `get_job_status` instead — the tool
description carries the same "don't block" contract the HTTP layer enforces.

Every tool call goes through `BackendClient` (`src/mcp_server/client.py`), which injects
the API key, retries on timeout or connection failure up to `MCP_HTTP_MAX_RETRIES` times,
and raises one `BackendError` with a specific `error_code` — `UPSTREAM_TIMEOUT` if it
timed out after retrying, `UPSTREAM_UNAVAILABLE` if it couldn't connect at all — rather
than two separate exception types for what's fundamentally the same situation from the
agent's point of view: *this call didn't work, here's whether retrying makes sense.*

## Idempotency

The problem idempotency solves: a network call can fail *after* the server already
created something, but before you got the response telling you so. Retry blindly, and if
the first call actually succeeded, you've now got two jobs for one request.

Every `POST /jobs` computes an idempotency key — either one you provide explicitly, or
one derived automatically by hashing `template_id`, `product_image`, `background_image`,
`prompt`, `image_count`, and `resolution` together into a SHA-256 digest. Two identical
requests always produce the same key, whether or not you ever thought about idempotency
at all.

```python
# src/services/job_service.py
claimed = await self._redis.set(
    idempotency_key(key), candidate_job_id, ex=self._settings.idempotency_ttl_seconds, nx=True
)
```

`SET key value NX EX <seconds>` — *set this, but only if the key doesn't already exist,
and auto-expire it after N seconds* — is one atomic Redis operation. That atomicity is
the whole point: two retries arriving at nearly the same instant can't both see "key is
free" and both create a job, because Redis only lets one of them win the `SET`. Whoever
loses looks up what the key already points to and returns *that* job instead.

```
Request 1  (key="abc-123")  → wins the claim → creates job-111 → returns job-111
(network blip, you retry)
Request 2  (key="abc-123")  → loses the claim → looks up abc-123 → returns job-111, not a new job
```

The mapping itself is really a time-bound cache, not a permanent record: both the
idempotency key (`IDEMPOTENCY_TTL_SECONDS`, 24h by default) and the job's own record
(`JOB_RECORD_TTL_SECONDS`, also 24h) expire on their own, so retried requests are only
deduplicated for a bounded window, and finished jobs don't accumulate in Redis forever.
One edge case is handled explicitly: if a key is still claimed but the job it points to
has somehow already expired or been deleted, `create_job` raises `409 CONFLICT` rather
than silently creating a new job under an old key — that failure mode is rare enough to
be worth naming instead of papering over.

## The job queue and workers

This is the part that took real engineering, so it gets its own section.

An earlier version of this backend ran rendering as an `asyncio.create_task` inside the
same process that handled the HTTP request. That works fine for a demo and fails in
exactly the ways a reviewer would ask about: if that one process dies, the job dies with
it; you can't run a second instance to handle more load, because there's nothing shared
between instances; and cancellation depended on an in-memory dictionary mapping job ids
to running tasks, which — being in memory — simply doesn't exist from any other process's
point of view.

The fix uses two Redis primitives that are already there for other reasons, so there's no
new infrastructure and no new dependency:

**A Stream** is an append-only log. `create_job` drops a one-field message —
`{job_id: "job-123"}` — onto `poster:jobs:stream`. That's the entire interaction between
the backend and a worker; the backend never talks to a worker directly, it just leaves a
note and returns.

**A Consumer Group** is a team of workers watching the same stream, with one guarantee
Redis enforces for you: each message goes to exactly one worker. Run five workers and a
hundred jobs come in, and Redis spreads them out on its own — that's the entire
horizontal-scaling story. Add a worker process, and it starts taking a share of the load
immediately, with zero code changes.

```python
# src/worker/stream.py
await redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)   # once, idempotently
await redis.xadd(STREAM_KEY, {"job_id": job_id})                            # the "enqueue" side
```

### What happens when a worker dies mid-job

This is the scenario an in-memory task registry can never handle, so it's worth being
exact about it:

1. Worker A claims `job-123`'s message via `XREADGROUP` and starts its 15-second sleep.
2. Worker A is killed at second 7. It never calls `XACK`.
3. The message sits in Worker A's **Pending Entries List** — Redis's per-consumer record
   of "checked out, not yet confirmed done." Redis doesn't know A is dead; it only knows
   this entry has been outstanding for a while.
4. Every worker's loop, before asking for new work, calls `XAUTOCLAIM` for anything idle
   longer than `JOB_STALE_CLAIM_SECONDS` (60s by default) and reassigns it.
5. Once that threshold passes, Worker B claims the orphaned message and reprocesses
   `job-123` from scratch.

I tested this by hand rather than trusting the theory: created a job, let a worker start
it, force-killed that worker mid-sleep, started a brand-new worker process, and watched it
reclaim and complete the exact same job a few seconds later. `JOB_STALE_CLAIM_SECONDS`
has to stay comfortably above `JOB_MAX_DURATION_SECONDS`, or a worker legitimately still
rendering something would get its own job stolen out from under it — the defaults (60s
vs. 20s) leave a wide margin.

Reprocessing a job that might have *already* half-finished is safe because `render_job`'s
first move is to check the job's current status and bail out immediately if it's not
still `processing` — so if Worker A had actually finished and crashed before acking, the
redo is a no-op, not a duplicate result.

### Cancellation without shared memory

A worker can't be told "stop" directly — there's no channel for that. Instead, instead of
one long sleep for the whole 5–20 second duration, `render_job` sleeps in
`JOB_POLL_INTERVAL_SECONDS` chunks (0.5s by default) and re-reads the job's status from
Redis between each one:

```python
while elapsed < duration:
    await asyncio.sleep(step)
    elapsed += step
    if (await redis.hget(job_key, "status")) != "processing":
        return   # someone cancelled it
```

Whoever flips the status — the cancel endpoint, running in a completely different
process — the worker notices within about half a second, on its own, and stops before
overwriting the cancellation with a late result.

### Keeping the worker itself alive

While testing crash recovery, I accidentally `FLUSHALL`'d Redis while a worker was
running — which wiped out the consumer group out from under it — and the worker crashed
with an unhandled `NOGROUP` error instead of recovering. That's a real bug, not a
hypothetical: a long-running service shouldn't die because one Redis call failed. The
fix wraps each loop iteration in its own `try/except`, logs the failure, re-creates the
group if needed, and keeps going after a one-second backoff — a transient Redis hiccup
now costs one slow iteration, not the whole process.

## Rate limiting and concurrency limits

Two separate guards, both enforced in Redis, both scoped per API key:

**Rate limiting** (`src/auth/rate_limit.py`) is a fixed-window counter —
`INCR` a `poster:ratelimit:<caller>` key, set its expiry on the first increment, reject
with `429` past `RATE_LIMIT_REQUESTS_PER_WINDOW` requests in `RATE_LIMIT_WINDOW_SECONDS`.
It's wired in at the router level for both `/templates` and `/jobs`, so it's one shared
budget across every authenticated endpoint — currently **10 requests per 60 seconds**.

**The concurrency cap** only applies to creating jobs. Each job's record stores a
`caller_id` — a truncated SHA-256 hash of the API key, so the raw credential is never
persisted anywhere, even internally. Creating a job adds it to
`poster:active_jobs:<caller_id>`; finishing, failing, or cancelling it removes it. If
that set's size is already at `MAX_CONCURRENT_JOBS_PER_KEY` (**5** by default),
`create_job` rejects with `429` before writing anything.

The concurrency check is deliberately **not atomic** — it's a `SCARD` followed later by a
`SADD`, so a true burst of simultaneous requests could overshoot the limit by a small
margin before the limit catches up. That's called out in a comment at the call site
(`job_service.py`) rather than hidden: it's an acceptable approximation for an abuse
guard, not something I'd ship for billing-grade enforcement without a Lua script or a
compare-and-swap loop.

## Error handling

Every error response has the same shape:

```json
{"success": false, "error": {"code": "CONFLICT", "message": "...", "details": null}, "timestamp": "..."}
```

and every message is written to tell the caller what to do next, not just that something
went wrong. The status codes in use each mean exactly one thing, consistently, across the
whole API:

| Status | Code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | The request itself is malformed — bad `image_count`, `prompt` too long |
| 401 | `UNAUTHORIZED` | Missing or wrong `X-API-Key` |
| 404 | `NOT_FOUND` | No job with that id (never existed, or expired) |
| 409 | `CONFLICT` | The request is valid, but conflicts with the resource's current state — cancelling a finished job, or an idempotency key whose job expired |
| 429 | `RATE_LIMITED` | Too many requests, or too many concurrent jobs, for this key |
| 503 / 504 | `UPSTREAM_UNAVAILABLE` / `UPSTREAM_TIMEOUT` | Redis couldn't be reached / didn't respond in time |

One exception class per failure mode (`src/exceptions/custom_exceptions.py`), not more —
a timeout and an unreachable server both surface as the *same* exception type on the MCP
client side (`BackendError`), distinguished only by an `error_code` field, because from
the caller's perspective they're the same question: did this work, and should I retry?

## Scalability, honestly assessed

**What scales cleanly, and why:** the backend is stateless — any number of replicas can
sit behind a load balancer, because every piece of state (job records, the queue,
idempotency keys, rate-limit counters) lives in Redis, never in a Python process's
memory. Idempotency is race-safe across replicas because the claim is one atomic Redis
operation. Workers scale by just running more of them; Redis's consumer-group guarantee
means adding a worker never causes duplicate work.

**What's still a real limitation, not fixed:** a single Redis instance is a single point
of failure for everything — this project doesn't set up Redis Cluster or Sentinel, which
a genuinely production deployment would want. The concurrency cap's check-then-act isn't
perfectly atomic, as noted above. And `XAUTOCLAIM` only recovers jobs a worker had
already claimed — if a job's *Redis hash* itself got written but its stream message was
somehow lost before any worker ever saw it (not something I've observed happening, but
not provably impossible), there's no separate sweep that would notice. For a mock
service standing in for a real one, I think this is the right amount of robustness to
build without gold-plating it.

## Getting started

**Requirements:** Python 3.13+, [Poetry](https://python-poetry.org/), a reachable
Redis 4+ instance (multi-field `HSET` support is required — this bit us once with an
ancient Redis build, see the note near the bottom of this file).

```bash
poetry install
cp .env.example .env     # fill in every key — Settings has no defaults; a missing one fails loudly at startup
```

Then, in three separate terminals:

```bash
poetry run uvicorn src.main:app --reload --port 8000     # the backend
poetry run python -m src.worker.poster_worker              # at least one worker — nothing renders without this
poetry run python -m src.mcp_server.server                 # the MCP server (stdio transport)
```

For interactive manual testing of the MCP tools without wiring up a full client, use the
MCP Inspector instead of the last line:

```bash
poetry run mcp dev src/mcp_server/server.py
```

To register this MCP server with an MCP-capable AI client, point it at
`poetry run python -m src.mcp_server.server` with this project's `.env` available to that
process.

## Running with Docker

```bash
docker compose up --build
```

One image, built once from the `Dockerfile` (Python 3.13, Poetry-installed dependencies),
run as two services — `app` and `worker` — plus a `redis` container.
`REDIS_HOST`/`REDIS_PORT` are overridden in `docker-compose.yml` to point both services at
the `redis` service, regardless of whatever `.env` says for local use. Scaling the worker
tier is one flag:

```bash
docker compose up --scale worker=3
```

Three worker containers, same queue, same guarantee that each job still renders exactly
once.

## Tests

```bash
poetry run pytest -v
```

33 tests across 7 files, run against a real Redis (database index 15, flushed before and
after each test) and an in-process ASGI transport — no separate backend process needed,
but Redis must be reachable. Tests that need a job to actually finish start a real worker
loop as a background task for the duration of that one test (the `worker` fixture) — the
same code that runs standalone in production, not a stand-in for it. Coverage includes:
template filtering, auth, input validation, the full job lifecycle through the real queue
(success, failure, cancellation, not-found, conflict), both idempotency paths plus the
expired-key edge case, rate limiting and the concurrency cap, the MCP tool layer's schema
and error messages, and the backend HTTP client's retry/timeout behavior.

Along the way, swapping the original `fakeredis`-backed test suite for a real Redis
instance caught a genuine bug: `fakeredis` happily accepted a multi-field `HSET` call that
an actual old Redis build would have rejected. That's the whole argument for not mocking
the one dependency everything else in this system depends on.

## A note on Redis on this dev machine

Worth mentioning in the interest of transparency: this development machine already had an
ancient "Redis on Windows 3.0.504" (from 2015) running as a background service on the
default port, predating multi-field `HSET` entirely — it's what caught the bug mentioned
above. Rather than fight Windows service permissions to remove it, a current Redis 8.10.2
build runs as a plain user process on port 6380 instead, and `.env` on this machine points
there. None of this affects anyone else running the project — point `REDIS_HOST` /
`REDIS_PORT` at whatever Redis you actually have.

## Transcript

[`transcript.md`](./transcript.md) holds a recorded session of an MCP client driving all
four tools end to end, including a validation failure and a cancellation.

---

## Written answers

**1. Why split create/status instead of one blocking tool? What changes at 5 or 20 minutes?**

A single blocking tool would hold the agent's turn open for up to 20 seconds with no way
to distinguish "still working" from "the connection died," and any retry on timeout risks
double-submitting the job. Splitting into `create_poster_job` (returns instantly) and
`get_job_status` (cheap, pollable) lets the agent reason, do other work, and recover from
network blips using the idempotency key instead of guessing. At 5 minutes, the same split
holds, but the agent should poll less aggressively (every 15–30s) and the backend should
expose a "my recent jobs" style tool so state survives a dropped conversation. At 20
minutes (e.g. video), polling in-context stops being viable — the agent would burn
turns/tokens waiting — so the design shifts to a push notification (webhook/callback) or
a durable job queue the agent checks back on in a later session entirely.

**2. Links or image data?**

Links. Tool results flow through the LLM's context; base64-encoding several 2k images
would be expensive in tokens, slow, and risks hitting context limits. URLs are cheap,
cacheable, CDN-friendly, and let the agent or a downstream UI fetch bytes only if needed.

**3. What to limit or never expose?**

Limit image count, prompt length, request rate, and concurrent jobs per API key, upload
size, and resolution tiers, to cap compute/storage cost and abuse. Never expose the API
key itself, internal infrastructure details (model/provider, internal URLs, stack
traces), or another tenant's job data in any tool output or error message.
