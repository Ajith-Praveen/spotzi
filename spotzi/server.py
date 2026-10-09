"""SpotZⁱ entry point.  Run:  python3 server.py   → http://localhost:8000   (or ./start.sh)"""

import os

from api.app import app  # noqa: F401  (uvicorn / ASGI servers import this)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("SPOTZI_PORT", "8000")))
