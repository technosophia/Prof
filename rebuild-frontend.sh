cd api
python -m compileall api.py api
cd ../frontend
npm run build
cd ..
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
