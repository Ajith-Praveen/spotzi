#!/bin/sh
# Start SpotZⁱ: local PostgreSQL cluster (data/pg, port 5544) + API/web server (port 8000).
cd "$(dirname "$0")"
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
PORT="${SPOTZI_PORT:-8000}"
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/manifest.webmanifest"; then
    echo "SpotZⁱ is already running at http://localhost:$PORT (use ./stop.sh to stop it)."
  else
    echo "Port $PORT is used by another program. Start on another port: SPOTZI_PORT=8010 ./start.sh"
  fi
  exit 0
fi
if [ -d data/pg ]; then
  pg_ctl -D data/pg status >/dev/null 2>&1 || pg_ctl -D data/pg -l data/pg/server.log -w start
fi
# Optional LLM settings (owner-readable file, never committed): LLM_PROVIDER=deepseek|zai|openai|anthropic|none, LLM_API_KEY=..., LLM_MODEL=...
if [ -f data/llm.env ]; then set -a; . data/llm.env; set +a; fi
echo "Starting SpotZⁱ at http://localhost:$PORT"
exec python3 server.py
