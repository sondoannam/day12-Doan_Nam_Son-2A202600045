# 📖 Quick Reference — Deployment Cheat Sheet

> Tài liệu tra cứu nhanh cho Day 12 Lab

---

## 🐳 Docker Commands

### Build & Run

```bash
# Build image
docker build -t <image-name>:<tag> .

# Run container
docker run -p <host-port>:<container-port> <image-name>

# Run với environment variables
docker run -e KEY=value -p 8000:8000 <image-name>

# Run detached (background)
docker run -d -p 8000:8000 <image-name>

# Run với volume
docker run -v $(pwd):/app -p 8000:8000 <image-name>
```

### Debug

```bash
# Xem logs
docker logs <container-id>
docker logs -f <container-id>  # Follow mode

# Exec vào container
docker exec -it <container-id> /bin/sh
docker exec -it <container-id> /bin/bash

# Inspect container
docker inspect <container-id>

# Xem processes
docker top <container-id>

# Xem resource usage
docker stats <container-id>
```

### Cleanup

```bash
# Stop container
docker stop <container-id>

# Remove container
docker rm <container-id>

# Remove image
docker rmi <image-name>

# Remove all stopped containers
docker container prune

# Remove all unused images
docker image prune -a

# Remove everything
docker system prune -a --volumes
```

---

## 🎼 Docker Compose Commands

```bash
# Start services
docker compose up

# Start detached
docker compose up -d

# Scale service
docker compose up --scale <service>=<replicas>

# Stop services
docker compose down

# View logs
docker compose logs
docker compose logs -f <service>

# Restart service
docker compose restart <service>

# Rebuild images
docker compose build
docker compose up --build
```

---

## 🚂 Railway Commands

```bash
# Install CLI
npm i -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Link to existing project
railway link

# Set variables
railway variables set KEY=value

# Deploy
railway up

# Get domain
railway domain

# View logs
railway logs

# Open dashboard
railway open

# Run command in Railway environment
railway run <command>
```

---

## 🎨 Render Deployment

### Via Dashboard

1. Push code to GitHub
2. Render Dashboard → New → Web Service
3. Connect repository
4. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables
6. Deploy

### Via Blueprint (render.yaml)

```yaml
services:
  - type: web
    name: my-agent
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: REDIS_URL
        fromService:
          name: redis
          type: redis
          property: connectionString
      - key: AGENT_API_KEY
        generateValue: true
      - key: LOG_LEVEL
        value: INFO

  - type: redis
    name: redis
    ipAllowList: []
```

---

## 🔐 Environment Variables Best Practices

### .env file

```bash
# .env (NEVER commit this)
OPENAI_API_KEY=sk-abc123
AGENT_API_KEY=secret-key-123
REDIS_URL=redis://localhost:6379
PORT=8000
LOG_LEVEL=INFO
```

### .env.example

```bash
# .env.example (commit this as template)
OPENAI_API_KEY=your-openai-key-here
AGENT_API_KEY=your-secret-key-here
REDIS_URL=redis://localhost:6379
PORT=8000
LOG_LEVEL=INFO
```

### Load trong Python

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    agent_api_key: str
    redis_url: str = "redis://localhost:6379"
    port: int = 8000
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 🏥 Health Check Patterns

### Liveness Probe

```python
@app.get("/health")
def health():
    """Kiểm tra process còn sống không"""
    return {"status": "ok"}
```

### Readiness Probe

```python
@app.get("/ready")
def ready():
    """Kiểm tra sẵn sàng nhận traffic không"""
    try:
        # Check dependencies
        redis_client.ping()
        db.execute("SELECT 1")
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(e)}
        )
```

### Trong Docker Compose

```yaml
services:
  agent:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

---

## 🔒 Authentication Patterns

### API Key

```python
from fastapi import Header, HTTPException

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.agent_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@app.post("/ask")
def ask(question: str, api_key: str = Depends(verify_api_key)):
    # ...
```

### JWT

```python
from jose import JWTError, jwt
from datetime import datetime, timedelta

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

---

## ⏱️ Rate Limiting Patterns

### Sliding Window (Redis)

```python
import redis
from datetime import datetime

r = redis.Redis()

def check_rate_limit(user_id: str, limit: int = 10, window: int = 60):
    """
    limit: số requests tối đa
    window: thời gian (seconds)
    """
    now = datetime.now().timestamp()
    key = f"rate:{user_id}"
    
    # Remove old entries
    r.zremrangebyscore(key, 0, now - window)
    
    # Count current requests
    current = r.zcard(key)
    
    if current >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Add new request
    r.zadd(key, {str(now): now})
    r.expire(key, window)
```

### Token Bucket

```python
def check_rate_limit_token_bucket(user_id: str, rate: int = 10):
    key = f"bucket:{user_id}"
    
    # Get current tokens
    tokens = int(r.get(key) or rate)
    
    if tokens <= 0:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Consume token
    r.decr(key)
    r.expire(key, 60)
```

---

## 💰 Cost Guard Pattern

```python
def check_budget(user_id: str, estimated_cost: float, monthly_limit: float = 10.0):
    """
    Track spending per user per month
    """
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    
    # Get current spending
    current = float(r.get(key) or 0)
    
    if current + estimated_cost > monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget exceeded. Current: ${current:.2f}"
        )
    
    # Add cost
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)  # 32 days
```

---

## 🔄 Graceful Shutdown Pattern

```python
import signal
import sys
import asyncio

shutdown_event = asyncio.Event()

def shutdown_handler(signum, frame):
    print("Received shutdown signal, gracefully shutting down...")
    shutdown_event.set()

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

@app.on_event("startup")
async def startup():
    # Initialize resources
    pass

@app.on_event("shutdown")
async def shutdown():
    # Cleanup resources
    print("Closing connections...")
    await redis_client.close()
    await db.disconnect()
    print("Shutdown complete")
```

---

## 📊 Structured Logging Pattern

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

# Setup
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Usage
logger.info("User request", extra={"user_id": "123", "endpoint": "/ask"})
```

---

## 🎯 Dockerfile Best Practices

### Multi-stage Build

```dockerfile
# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy only necessary files
COPY --from=builder /root/.local /root/.local
COPY app/ ./app/

# Non-root user
RUN useradd -m appuser
USER appuser

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### .dockerignore

```
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
.git
.gitignore
.dockerignore
.env
.env.*
!.env.example
*.md
!README.md
.vscode/
.idea/
*.log
.DS_Store
```

---

## 🧪 Testing Endpoints

### cURL

```bash
# GET request
curl http://localhost:8000/health

# POST with JSON
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret" \
  -d '{"question": "Hello"}'

# With Bearer token
curl -X POST http://localhost:8000/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'

# Save response to file
curl http://localhost:8000/ask -o response.json

# Show response headers
curl -i http://localhost:8000/health

# Follow redirects
curl -L http://localhost:8000/redirect
```

### HTTPie (more user-friendly)

```bash
# Install
pip install httpie

# GET
http localhost:8000/health

# POST
http POST localhost:8000/ask \
  X-API-Key:secret \
  question="Hello"

# Pretty print
http --pretty=all localhost:8000/ask
```

### Python requests

```python
import requests

# GET
response = requests.get("http://localhost:8000/health")
print(response.json())

# POST with auth
response = requests.post(
    "http://localhost:8000/ask",
    headers={"X-API-Key": "secret"},
    json={"question": "Hello"}
)
print(response.json())
```

---

## 🔍 Debugging Tips

### Check if port is in use

```bash
# macOS/Linux
lsof -i :8000

# Kill process on port
kill -9 $(lsof -t -i:8000)
```

### Check container networking

```bash
# List networks
docker network ls

# Inspect network
docker network inspect <network-name>

# Test connectivity between containers
docker exec <container-id> ping <other-container-name>
```

### View environment variables in container

```bash
docker exec <container-id> env
```

### Copy files from container

```bash
docker cp <container-id>:/app/logs/app.log ./local-app.log
```

---

## 📈 Performance Tips

### Optimize Docker build

```dockerfile
# Cache dependencies layer
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy code (changes frequently)
COPY . .
```

### Use .dockerignore

Giảm context size → build nhanh hơn.

### Multi-stage builds

Giảm image size → deploy nhanh hơn.

### Use slim base images

```dockerfile
# ❌ Large (1GB+)
FROM python:3.11

# ✅ Smaller (150MB)
FROM python:3.11-slim

# ✅ Smallest (50MB, but harder to debug)
FROM python:3.11-alpine
```

---

## 🎓 12-Factor App Checklist

- [ ] **I. Codebase:** One codebase tracked in Git
- [ ] **II. Dependencies:** Explicitly declare (requirements.txt)
- [ ] **III. Config:** Store in environment variables
- [ ] **IV. Backing services:** Treat as attached resources
- [ ] **V. Build, release, run:** Strictly separate stages
- [ ] **VI. Processes:** Execute as stateless processes
- [ ] **VII. Port binding:** Export services via port binding
- [ ] **VIII. Concurrency:** Scale out via process model
- [ ] **IX. Disposability:** Fast startup and graceful shutdown
- [ ] **X. Dev/prod parity:** Keep environments similar
- [ ] **XI. Logs:** Treat logs as event streams
- [ ] **XII. Admin processes:** Run as one-off processes

---

## 🆘 Common Errors & Solutions

### "Port already in use"

```bash
# Find and kill process
lsof -ti:8000 | xargs kill -9
```

### "Cannot connect to Redis"

```bash
# Check Redis is running
docker ps | grep redis

# Check connection string
echo $REDIS_URL
```

### "Module not found"

```bash
# Rebuild with --no-cache
docker build --no-cache -t myapp .

# Check PYTHONPATH
docker exec <container> python -c "import sys; print(sys.path)"
```

### "Permission denied"

```dockerfile
# Fix: Use non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
```

---

**Keep this handy during the lab! 📌**
