#!/bin/sh
# Container entrypoint: make sure the private per-user HOME exists on the
# runtime volume, then run the requested command (default: sleep infinity).
# It never creates, reads or prints credentials.
set -eu
umask 077

home="${HOME:-/data/home}"
case "$home" in
  /*) ;;
  *) echo "usage-entrypoint: HOME must be an absolute path" >&2; exit 1 ;;
esac

if [ -L "$home" ]; then
  echo "usage-entrypoint: refusing symlinked HOME $home" >&2
  exit 1
fi
if [ ! -d "$home" ]; then
  mkdir -p "$home"
fi
chmod 0700 "$home"

if [ -d /data ] && ! grep -qs ' /data ' /proc/mounts; then
  echo "usage-entrypoint: warning: /data is not a mounted volume; logins and" \
       "accounts will be lost on redeploy. Attach a Railway volume at /data." >&2
fi

cd "$home"
exec "$@"
