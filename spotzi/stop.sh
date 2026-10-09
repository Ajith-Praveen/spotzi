#!/bin/sh
# Stop SpotZⁱ server and the local PostgreSQL cluster.
cd "$(dirname "$0")"
lsof -ti tcp:"${SPOTZI_PORT:-8000}" -sTCP:LISTEN | xargs kill 2>/dev/null   # never kill clients (e.g. the browser) connected to the port
export LC_ALL=en_US.UTF-8
[ -d data/pg ] && pg_ctl -D data/pg -m fast stop
