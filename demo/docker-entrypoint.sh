#!/bin/sh
# Demo container entrypoint: on first start, fill /data from the read-only clean copy in /demo, then hand over to the image's own entrypoint, which
# gives /data to the headwind user, brings the database up to this version (python -m database migrate) and drops root before Gunicorn starts.
# The nightly reset (services/demo.py) restores from the same clean files, so /data is disposable.
set -e
mkdir -p /data/avatars
if [ ! -f /data/bike.db ]; then
    cp /demo/pristine.db /data/bike.db
    if [ -d /demo/bikeimg ]; then
        mkdir -p /data/bikeimg
        cp -r /demo/bikeimg/. /data/bikeimg/
    fi
fi
# compose's entrypoint: clears the image's CMD, so the Gunicorn command is given here (the same as the image's, apart from the shorter timeout)
exec /app/docker-entrypoint.sh gunicorn --workers "${WEB_WORKERS:-2}" --threads 8 --bind 0.0.0.0:5001 --timeout 120 \
    --log-level "${LOG_LEVEL:-info}" 'app:create_app()'
