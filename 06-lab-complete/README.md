# Agentic Job Hunter Backend

Production-ready FastAPI backend for the Day 12 Agentic Job Hunter lab. The stack uses Redis for stateless session storage, OpenAI as the primary LLM provider with Gemini fallback, API-key authentication, Redis-backed rate limiting, monthly cost controls, structured JSON logging, and Docker deployment behind an Nginx load balancer.

## Architecture

- `app`: FastAPI application replicas serving the API on internal port `8000`
- `redis`: shared Redis instance for sessions, rate limiting, and budget tracking
- `nginx`: public reverse proxy and load balancer exposing the service on port `80`

Nginx routes external traffic to the FastAPI replicas using Docker DNS, so horizontal scaling is done with Docker Compose:

```bash
docker compose up --build --scale app=3
```

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Valid OpenAI and Gemini API keys

## Configuration

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Update `.env` with real secrets:

```env
AGENT_API_KEY=replace-with-a-shared-api-key
OPENAI_API_KEY=replace-with-openai-api-key
GEMINI_API_KEY=replace-with-gemini-api-key
```

Important variables:

- `AGENT_API_KEY`: required on every protected request via the `X-API-Key` header
- `OPENAI_API_KEY`: primary provider key
- `GEMINI_API_KEY`: fallback provider key
- `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`: per-user request throttling
- `MONTHLY_BUDGET_USD` and `REQUEST_RESERVE_USD`: monthly cost guard settings
- `REDIS_URL`: should remain `redis://redis:6379/0` for Docker Compose

## Run With Docker Compose

Start the full stack with one FastAPI replica:

```bash
docker compose up --build
```

Start in the background:

```bash
docker compose up --build -d
```

Scale the FastAPI service to three replicas behind Nginx:

```bash
docker compose up --build -d --scale app=3
```

Stop the stack:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f nginx
docker compose logs -f app
docker compose logs -f redis
```

## Local Development Without Docker

If you want to run the API directly on your machine, use the existing Conda environment:

```bash
conda activate vinuni_ai
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

You also need a Redis instance running locally and `REDIS_URL` set to it, for example:

```env
REDIS_URL=redis://localhost:6379/0
```

## API Endpoints

- `GET /health`: liveness probe
- `GET /ready`: readiness probe, including Redis connectivity
- `POST /session/init`: stores CV and job description for a user session
- `POST /ask`: asks a question using either general chat mode or stored CV/JD context
- `POST /chat`: alias route for interactive chat requests

## Example Requests

Health check through Nginx:

```bash
curl http://localhost/health
```

Initialize a CV/JD session:

```bash
curl -X POST http://localhost/session/init \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{
    "user_id": "alice",
    "cv_text": "Backend engineer with FastAPI, Redis, Docker, and CI/CD experience.",
    "jd_text": "Hiring a Python backend engineer with production API and container deployment skills."
  }'
```

Ask a follow-up question:

```bash
curl -X POST http://localhost/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{
    "user_id": "alice",
    "question": "What should I emphasize in my CV summary?"
  }'
```

General chat without prior session initialization:

```bash
curl -X POST http://localhost/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{
    "user_id": "guest-user",
    "question": "How can I tailor my resume for backend roles?"
  }'
```

## Deployment Notes

- The FastAPI containers are intentionally not published directly to the host. Only Nginx exposes port `80`.
- Docker Compose scaling works because the `app` service no longer uses a fixed container name.
- Nginx balances traffic across `app` replicas using Docker's internal DNS resolver at `127.0.0.11`.
- Redis is internal-only in the Compose network and is not exposed publicly.

## Troubleshooting

- If port `80` is already in use, stop the conflicting process before starting the stack.
- If `/ready` returns `503`, inspect Redis and app logs:

```bash
docker compose logs -f redis
docker compose logs -f app
```

- If requests fail with `401`, verify the `X-API-Key` header matches `AGENT_API_KEY`.
- If requests fail with `429`, the per-user rate limit has been reached.
- If requests fail with `402`, the monthly budget guard has blocked additional usage.