#!/bin/sh
# The routing engine the demo's tracks are drawn with (demo/generate_demo_db.py), in Docker, on 127.0.0.1 only, used only while building.
#   demo/brouter.sh start    fetch BRouter and the map tile for Great Britain's middle (once, about 150 MB), then run it
#   demo/brouter.sh stop     stop and remove it
# Everything is kept in $DEMO_BUILD_DIR/brouter (default ~/headwind-demo-build/brouter), outside the repo.
# The tile is W5_N50 (5°W to 0°, 50°N to 55°N): every area in demo/demo_areas.py is inside it. An area outside it needs its own tile.
set -e
VERSION=1.7.10
TILES="W5_N50"
DIR="${DEMO_BUILD_DIR:-$HOME/headwind-demo-build}/brouter"
NAME=headwind-demo-brouter
PORT="${DEMO_BROUTER_PORT:-17777}"

case "$1" in
start)
    mkdir -p "$DIR/segments4" "$DIR/customprofiles"
    if [ ! -f "$DIR/release/brouter-$VERSION/brouter-$VERSION-all.jar" ]; then
        curl -fsSL -o "$DIR/brouter.zip" "https://github.com/abrensch/brouter/releases/download/v$VERSION/brouter-$VERSION.zip"
        unzip -q -o "$DIR/brouter.zip" -d "$DIR/release"
    fi
    for t in $TILES; do
        [ -f "$DIR/segments4/$t.rd5" ] || curl -fsSL -o "$DIR/segments4/$t.rd5" "https://brouter.de/brouter/segments4/$t.rd5"
    done
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" -p "127.0.0.1:$PORT:17777" \
        -v "$DIR/release/brouter-$VERSION:/brouter:ro" -v "$DIR/segments4:/segments4:ro" -v "$DIR/customprofiles:/customprofiles" -w /brouter \
        eclipse-temurin:21-jre java -Xmx2g -cp "brouter-$VERSION-all.jar" btools.server.RouteServer /segments4 /brouter/profiles2 /customprofiles 17777 4 0.0.0.0
    echo "BRouter on http://127.0.0.1:$PORT"
    ;;
stop)
    docker rm -f "$NAME"
    ;;
*)
    echo "usage: $0 start|stop" >&2
    exit 1
    ;;
esac
