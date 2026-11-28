# Headwind public demo

A Headwind anyone can try. Visitors press **Enter the demo** on the sign-in page (or sign in as `test` / `test`, e.g. from the phone app) and see a
made-up athlete's activities, food diary, gear and health. They can look around and try the harmless things (log a meal, add water, assign a bike).
Anything that could change settings, reach other servers or touch files is refused. The whole database resets every night at 04:00 from a clean copy,
and the dates move forward a week at a time so the data always ends yesterday.

## What demo mode does (`HEADWIND_DEMO=1`, `services/demo.py`)
- **Everything is shut unless it's on a list.** Writes open only if they're in `ALLOWED_WRITES`, reads only if they're in `SAFE_READS`. `DENIED_ENDPOINTS` names the ones
  that stay shut on purpose: the server's logs and diagnostics, backups, the update check, contacts, live-tracking links, proxies and peer feeds.
  `tests/test_demo_mode.py` fails while any page or API is on none of the lists, so a new page needs someone to look at what it shows before it opens in the demo.
- **Nothing on the network around it.** In demo mode the app refuses every outgoing connection to a private address (home network, link-local, CGNAT),
  whatever a setting says, and starts no background work that talks to the network: only the nightly reset.
- Each visitor is rate-limited (`DEMO_RATE_PER_MIN`, default 300 a minute; a write counts 4). Their address comes from Cloudflare's `CF-Connecting-IP`.
- The reset migrates the clean copy to the running version before swapping it in, so a clean copy built by an older Headwind still works. It
  also makes any map summaries (the lines the heatmap and segments read, `services/tracks.py`) the copy lacks, so the first visitor after a reset
  doesn't wait for them. The builder saves them in `pristine.db` already; a new version that makes them another way has the reset make them again
  (a few seconds of the worker's time). The demo's first start does the same for the copy it starts on. The log says how long each reset took.
- `/demo/health` (for the health check) and `/demo/counter.gif` (the visitor counter) are public.

## The data
A made-up athlete, Alex, over the last two years: road, gravel, mountain-bike and e-bike rides, runs, walks and hikes, paddles on lakes, and
indoor rides, pool swims and gym sessions, in four national parks (the Peak District, the Lake District, Snowdonia and the Yorkshire Dales), a few
weeks in each at a time. A friend, Sam, rides and runs with Alex on some days. Around them: four bikes with parts and a service log, shoes and a
board, a food diary, water, weigh-ins, steps, sleep and recovery, goals, two challenges, planned routes and the AI coach's notes.

No real track is in it. Every route is drawn by a routing engine ([BRouter](https://github.com/abrensch/brouter), on OpenStreetMap) between
public places in `demo_areas.py` (stations, visitor centres, village car parks, summits), or across a lake from OpenStreetMap's outline of it.
Only coordinate-free patterns come from a real database (`extract_patterns.py`): how often each sport is done and when, how far, and how speed,
heart rate, cadence and power go with the gradient. Every activity is then stored the way an upload is, so Headwind works out its weather
(Open-Meteo's archive, for its place and day), best efforts, segment efforts and records itself. The segments are on the biggest climbs of the
favourite routes.

| File | What it does |
|---|---|
| `extract_patterns.py` | the real database (read-only) to `patterns.json`: numbers only, checked before it's saved |
| `generate_demo_db.py` | `patterns.json` to `out/pristine.db` and `out/bikeimg/`, with `demo_areas.py` and `build_fiction.py` |
| `audit_demo_db.py` | fails if any name, id, setting, token or place of the real database is in the demo (it prints how far, never where) |
| `publish_demo.py` | all three, then the copy to the demo's machine and its reset: one command |
| `brouter.sh` | the routing engine in Docker on 127.0.0.1, only while building |

The audit keeps every generated point 3 km from the places the real activities often start or finish at, and from its privacy zones. A start
that's too close comes out of `demo_areas.py`; for a public place you use yourself (a trail centre), `--allow-near <its name>` (in
`DEMO_AUDIT_ALLOW_NEAR`, below) lets it through.

`out/` is never committed. Routes, lake outlines and the build are kept in `~/headwind-demo-build` (`DEMO_BUILD_DIR`), outside the repo, so a
second build asks the routing engine and OpenStreetMap nothing new.

## Build it and publish it
On the machine with the real data, never on the demo's (it gets only the audited output):

1. `demo/brouter.sh start` (the first time it fetches BRouter and the one map tile all four areas are in, about 150 MB).
2. Write `demo/publish.env` (ignored by git: it names your machines):

       HEADWIND_SOURCE_DB=/path/to/your/bike.db
       DEMO_PUSH_HOST=<ssh destination: the demo's machine, or a Proxmox host>
       # DEMO_PUSH_VIA=pct and DEMO_PUSH_CT=<container id>, to go through the Proxmox host with pct push
       # DEMO_PUSH_DIR=/opt/headwind-demo/out
       # DEMO_AUDIT_ALLOW_NEAR=<a start's name in demo_areas.py>

3. `python3 demo/publish_demo.py` (with the venv's Python, as it uses Headwind's own code): patterns, generation, the audit, then the copy and
   `reset.flag`. `--no-push` stops before the copy, so you can look at `~/headwind-demo-build/out` first; `--push-only` then copies it.
4. `demo/brouter.sh stop`.

A build takes a few minutes. `pristine.db` goes over as one file (no WAL: the demo opens it read-only) and is swapped in whole.

## Run it (a machine on a home network, through a Cloudflare tunnel)
1. In Cloudflare Zero Trust (Networks, Tunnels), create a tunnel and give it a public hostname whose service is `http://headwind-demo:5001`.
2. Write `demo/.env` (ignored by git), `chmod 600`:

       DEMO_SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
       TUNNEL_TOKEN=<the tunnel's token>
       DEMO_APP_URL=https://<the public hostname>
       # DEMO_IMAGE=ghcr.io/atombrake/headwind:<version>   (default :beta)

3. Put the clean copy in `demo/out/` (**Build it and publish it**, below), then `docker compose -f demo/docker-compose.demo.yml --env-file demo/.env up -d`.

The demo container is on a Docker network with no way out (`internal: true`). It can reach neither the internet nor the home network, and only
`cloudflared` can reach it. No port is published on the host. Food search then uses the foods already cached in the demo's database. To check the
isolation from inside: `docker exec headwind-demo python -c "import urllib.request; urllib.request.urlopen('http://<your router>', timeout=3)"` must fail.

## Check it before it goes online
No tunnel is needed for this. Put a stand-in for `cloudflared` in an override file (say `stub.yml`) and use a throwaway `TUNNEL_TOKEN`:

    services:
      cloudflared:
        image: alpine:3
        entrypoint: ["sh", "-c", "sleep infinity"]
        command: []

`docker compose -f demo/docker-compose.demo.yml -f stub.yml --env-file <your env file> up -d`, then:
- `docker logs headwind-demo` shows the database steps and Gunicorn starting, and `docker ps` shows it healthy, with no port on the host.
- From the stand-in, which is on the demo's network and an ordinary one, the demo answers: `docker exec headwind-demo-tunnel wget -qO- http://headwind-demo:5001/demo/health`.
  The same container reaching the internet shows that its second network works.
- From the demo container, nothing does: a connection to a public address (`1.1.1.1:443`), your router, your computer's address on the home
  network and `host.docker.internal` must each fail, and so must a DNS lookup.

`docker compose ... down -v` removes it all again.

## Update
- **New Headwind version:** `docker compose -f demo/docker-compose.demo.yml --env-file demo/.env pull && ... up -d`. The database is migrated at start.
- **New data:** `python3 demo/publish_demo.py` (above). By hand: replace `out/pristine.db`, then `touch` `reset.flag` in the data volume (the
  worker resets within 30 s), or remove the `demo-data` volume and start again. The visitor counter lives in that volume, so removing it starts
  the count again.
