#!/bin/sh
# Runs the command (gunicorn, or whatever `docker run` was given) as the unprivileged headwind user.
# Images before this one ran as root, so an existing data folder belongs to root: while still root, hand over whatever
# isn't the user's yet (only those, so a later start doesn't rewrite the whole folder), then drop root with setpriv.
# Started with --user, it's already not root and changes nothing. If something can't be handed over (a read-only data
# folder, NFS that maps root to nobody), it says so and stays root, as before, rather than start an app that can't
# read its own files.
# Before Gunicorn, the database is brought up to this version (python -m database migrate, database.STEPS), so a long
# change on a big database isn't cut short by Gunicorn's worker timeout. If the database is from a newer Headwind, it
# stops there, saying so.
set -e

mkdir -p /data/avatars /app/.garmin_tokens 2>/dev/null || true   # /data/avatars is the target of /app/static/avatars

run_as=""
if [ "$(id -u)" = 0 ]; then
    uid=$(id -u headwind)
    gid=$(id -g headwind)
    if find /data /app/.garmin_tokens \( ! -user "$uid" -o ! -group "$gid" \) -exec chown -h "$uid:$gid" {} + 2>/dev/null; then
        run_as="setpriv --reuid=$uid --regid=$gid --init-groups --no-new-privs env HOME=/home/headwind"
    else
        echo "Headwind: couldn't give the headwind user (uid $uid) the files in /data and /app/.garmin_tokens, so it runs as root." >&2
        echo "Headwind: make them writable, or run the container with --user, to stop running as root." >&2
    fi
fi

case "$*" in
    *gunicorn*) $run_as python -m database migrate ;;
esac
exec $run_as "$@"
