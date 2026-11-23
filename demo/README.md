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
- The reset migrates the clean copy to the running version before swapping it in, so a clean copy built by an older Headwind still works.
- `/demo/health` (for the health check) and `/demo/counter.gif` (the visitor counter) are public.

## The data
The clean copy is `demo/out/pristine.db` (and `demo/out/bikeimg/`), which is never committed. The plan (TODO.md, Demo) is a builder that
**generates** every track on real roads and paths in an area far from home, and takes only coordinate-free patterns from a real database.
Until that builder exists, don't publish a demo built with `build_demo_db.py`. That builder keeps real tracks (with the often-used start and finish
places cleared), so a heatmap of all of them still shows where those places are.

## Run it (a machine on a home network, through a Cloudflare tunnel)
1. In Cloudflare Zero Trust (Networks, Tunnels), create a tunnel and give it a public hostname whose service is `http://headwind-demo:5001`.
2. Write `demo/.env` (ignored by git), `chmod 600`:

       DEMO_SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
       TUNNEL_TOKEN=<the tunnel's token>
       DEMO_APP_URL=https://<the public hostname>
       # DEMO_IMAGE=ghcr.io/atombrake/headwind:<version>   (default :beta)

3. Put the clean copy in `demo/out/`, then `docker compose -f demo/docker-compose.demo.yml --env-file demo/.env up -d`.

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
- **New data:** replace `demo/out/pristine.db`, then `touch` `reset.flag` in the data volume (the worker resets within 30 s), or remove the
  `demo-data` volume and start again. The visitor counter lives in that volume, so removing it starts the count again.
