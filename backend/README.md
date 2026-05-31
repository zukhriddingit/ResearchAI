# DeepPaper Backend

FastAPI service for the DeepPaper hackathon starter.

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## Demo Flow

```bash
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
curl -s -X POST "http://localhost:8000/api/sessions/$SESSION_ID/papers/load" \
  -H "content-type: application/json" \
  -d '{"source_type":"demo","source":"lora"}'
curl -s -X POST "http://localhost:8000/api/sessions/$SESSION_ID/citations/cit_adapter/click"
```

The demo works without API keys. External arXiv, Semantic Scholar, GitHub, Anthropic, and W&B integrations are optional and must fail gracefully.

