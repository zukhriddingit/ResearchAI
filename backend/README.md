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

## Upload Papers

The backend accepts PDF and text uploads:

```bash
curl -s -X POST "http://localhost:8000/api/sessions/$SESSION_ID/papers/upload" \
  -F "file=@/path/to/paper.pdf"
```

The upload endpoint extracts text locally and parses it into the current session. If Cloudinary credentials are configured, it also stores the original file as a raw asset.

## Cloudinary Setup

Put these in `backend/.env`:

```bash
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
CLOUDINARY_UPLOAD_FOLDER=researchai/papers
```

Cloudinary storage is optional. Missing Cloudinary env vars do not block local parsing.

## W&B Setup

Put your key in `backend/.env`:

```bash
cp .env.example .env
```

Then edit:

```bash
WANDB_API_KEY=your_wandb_api_key_here
WANDB_INFERENCE_PROJECT=your-team/researchai
WEAVE_PROJECT=your-team/researchai
```

`WANDB_INFERENCE_PROJECT` is used for W&B Serverless Inference usage tracking. `WEAVE_PROJECT` is where traces appear in Weave. They can point at the same W&B project.
