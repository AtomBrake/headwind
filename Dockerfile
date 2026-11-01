FROM python:3.14-slim AS build

# gcc only for a dependency with no wheel for this platform; it stays in this stage, out of the image
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The exact versions and hashes in requirements.lock (pip-compile from requirements.txt: see the README to refresh it)
COPY requirements.lock .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock


FROM python:3.14-slim

WORKDIR /app

# The app runs as this user (docker-entrypoint.sh drops root at start). uid 1000, so on a Linux host a bind-mounted
# ./data belongs to the usual first user.
RUN groupadd --gid 1000 headwind && useradd --uid 1000 --gid headwind --create-home --shell /usr/sbin/nologin headwind

COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY . .

# Stamp build time so the settings page can show it and check for updates
RUN date -u +%Y-%m-%dT%H:%M:%SZ > /app/build_time.txt

# Persistent data lives outside the image; rider avatars are symlinked into the /data volume so they survive upgrades.
# The code stays root's; the user gets the data folders and .env, which Settings writes a changed login to.
RUN mkdir -p /data/avatars /app/.garmin_tokens && rm -rf /app/static/avatars && ln -s /data/avatars /app/static/avatars \
    && touch /app/.env && chown headwind:headwind /data /data/avatars /app/.garmin_tokens /app/.env \
    && chmod 755 /app/docker-entrypoint.sh

EXPOSE 5001

ENV DATABASE_URL=/data/bike.db

# /login needs no sign-in. The start period covers a first start on a new version, which migrates the database before it
# answers (minutes on a big one); a check that passes earlier ends it.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10m --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/login', timeout=8)"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Single worker (background threads — MQTT heartbeat, Garmin sync — must not be duplicated) with several request threads, so a long
# streaming sync or import no longer blocks every other page.
# Timeout 300s covers large Strava export imports.
# Logging (services/logs.py): LOG_LEVEL (default INFO; DEBUG when chasing a fault) sets Gunicorn's level too. Headwind logs each request itself,
# with an id, so Gunicorn's access log stays off; the log files go to /data/logs.
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 8 --bind 0.0.0.0:5001 --timeout 300 --log-level \"${LOG_LEVEL:-info}\" 'app:create_app()'"]
