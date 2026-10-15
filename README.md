# RoadSense — AI road-damage reporter

Upload a road photo → a YOLO26 model trained on RDD2022 finds potholes and cracks →
reports within 20 m are merged into hotspots on a live map → Gemini drafts a complaint letter
in English or Telugu.

> Work in progress. Full README with screenshots, metrics and the live link comes on Day 4.

## Structure
- `ml/` — Colab notebook that trains the model
- `backend/` — FastAPI + PostgreSQL/PostGIS + ONNX Runtime + Gemini
- `frontend/` — React website (coming next)

## Run the backend locally (Windows PowerShell)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # then fill in .env
python scripts/init_db.py
uvicorn app.main:app --reload   # open http://127.0.0.1:8000/docs
python -m pytest                # tests
```
