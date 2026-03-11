python -m compileall api
npm --prefix frontend run build

uvicorn api:app --host 0.0.0.0 --port 8000 --reload
