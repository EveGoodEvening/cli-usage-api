# Sourced from /etc/bash.bashrc (Debian's /etc/profile also sources it for
# login bash). Some shells do not inherit the image ENV: Railway's web console
# starts a login shell with HOME=/root from /etc/passwd and a PATH reset by
# /etc/profile. Restore the image's values so CLI logins land on the volume
# and `usage` is found. Keep these in sync with the Dockerfile ENV.

# Private files by default (login state, config edits); the official CLIs
# still set their own credential-file modes.
umask 077

if [ "${HOME-}" != /data/home ]; then
  if [ "${PWD-}" = "${HOME-}" ]; then
    cd /data/home 2>/dev/null || true
  fi
  export HOME=/data/home
fi

for usage_api_dir in /opt/grok/bin /app/.venv/bin; do
  case ":${PATH-}:" in
    *":$usage_api_dir:"*) ;;
    *) PATH="$usage_api_dir${PATH:+:$PATH}" ;;
  esac
done
unset usage_api_dir
export PATH
