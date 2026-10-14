"""
PredictaStock Server Launcher
Runs FastAPI backend on 127.0.0.1:8000
"""
import sys
from pathlib import Path
import uvicorn

# Ensure backend root is in python path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
