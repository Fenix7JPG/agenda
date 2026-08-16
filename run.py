"""Arranque del servidor web.

Uso:
    python run.py

Equivalente a:
    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
