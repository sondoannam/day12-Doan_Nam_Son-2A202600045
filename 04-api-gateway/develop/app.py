"""
BASIC — API Key Authentication

Lớp bảo vệ đơn giản nhất: kiểm tra header X-API-Key.
Phù hợp cho: internal API, B2B, MVP.

Chạy:
    AGENT_API_KEY=my-secret-key python app.py

Test:
    # Có key → 200
    curl -H "X-API-Key: my-secret-key" -X POST \\
         -H "Content-Type: application/json" \\
         -d '{"question":"hello"}' \\
         http://localhost:8000/ask

    # Không có key → 401
    curl -X POST -H "Content-Type: application/json" \\
         -d '{"question":"hello"}' \\
         http://localhost:8000/ask
"""
import os


from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
import uvicorn
from utils.mock_llm import ask

app = FastAPI(title="Agent with API Key Auth")

# ──────────────────────────────────────
# API Key setup
# ──────────────────────────────────────
API_KEY = os.getenv("AGENT_API_KEY", "demo-key-change-in-production")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Dependency: kiểm tra API key.
    Inject vào bất kỳ endpoint nào cần bảo vệ.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Include header: X-API-Key: <your-key>",
        )
    if api_key != API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )
    return api_key


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@app.get("/")
def root():
    """Public endpoint — không cần auth"""
    return {"message": "AI Agent API", "auth": "Required for /ask"}


@app.post("/ask")
async def ask_agent(
    question: str,
    _key: str = Depends(verify_api_key),  # ✅ require auth
):
    """Protected endpoint — cần X-API-Key header"""
    return {
        "question": question,
        "answer": ask(question),
    }


@app.get("/health")
def health():
    """Health check — public (platform cần access)"""
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"API Key: {API_KEY}")
    print(f"Test: curl -H 'X-API-Key: {API_KEY}' http://localhost:{port}/ask?question=hello")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
