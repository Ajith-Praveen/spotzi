#!/bin/sh
# Stop SpotZ^i server and the local PostgreSQL cluster.
cd "$(dirname "$0")"
lsof -ti:"${SPOTZI_PORT:-8000}" | xargs kill 2>/dev/null
export LC_ALL=en_US.UTF-8
[ -d data/pg ] && pg_ctl -D data/pg -m fast stop
