# Railway / container image for the read-only usage API backend.
#
# The image installs Python, this project, Node.js and the three first-party CLIs,
# then idles with `sleep infinity`. Log in to the CLIs, configure accounts and start
# `usage api serve` manually through `railway ssh` (see docs/deploy-railway.md).
# No credential, token or login state is baked into the image: everything per-user
# lives under HOME=/data/home on the Railway volume mounted at /data at runtime.
#
# Pinned versions (update deliberately; record the source when changing them):
#   uv           0.13.6    ghcr.io/astral-sh/uv (includes the CPython 3.12.16 catalog)
#   Node.js      22.23.4   LTS "Jod", https://nodejs.org/dist/v22.23.4/SHASUMS256.txt
#   Claude Code  2.1.308   npm @anthropic-ai/claude-code (npm "stable" dist-tag)
#   Codex CLI    0.165.0   npm @openai/codex ("latest" dist-tag)
#   Grok Build   1.0.70    https://x.ai/cli/stable ; artifacts named by
#                          https://x.ai/cli/install.sh (grok-<ver>-linux-<arch>.gz).
#                          xAI publishes no checksums; the SHA-256 values below were
#                          computed from the downloaded artifacts on 2026-10-29
#                          (trust on first use), so a changed artifact fails the build.

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# CPython 3.12.16 blocks compromised eMudhra intermediate keys in ssl, including
# cross-signed chains: https://blog.python.org/2026/10/python-3152-31410-31318-31216-31118/
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ARG TARGETARCH
ARG NODE_VERSION=22.23.4
ARG NODE_SHA256_AMD64=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
ARG NODE_SHA256_ARM64=6287aa46b6c375d816e63ae66d024fbbfd70404825aabdfdf898a970871d2f4b
ARG GROK_VERSION=1.0.70
ARG GROK_SHA256_AMD64=11d27a30adfb75c4b9b180072ab27412a1916f054ff5497ab70fb9a77d304bcc
ARG GROK_SHA256_ARM64=0d9e47fc2cb14db2f52f99e9289c41b3723b64de05c284a9f18c2e8df52550cf

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Use Debian's vendor-maintained CA fix, not an application root blacklist.
# https://packages.debian.org/bookworm/ca-certificates (security update)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git tmux procps less tini xz-utils \
 && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge '20250419~deb12u2' \
 && rm -rf /var/lib/apt/lists/*

# Node.js (official tarball, checksum-verified) for the npm-distributed CLIs.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) node_arch=x64;   node_sha="${NODE_SHA256_AMD64}" ;; \
      arm64) node_arch=arm64; node_sha="${NODE_SHA256_ARM64}" ;; \
      *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && tarball="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
 && curl --proto '=https' --proto-redir '=https' -fsSLo "/tmp/${tarball}" "https://nodejs.org/dist/v${NODE_VERSION}/${tarball}" \
 && echo "${node_sha}  /tmp/${tarball}" | sha256sum -c - \
 && tar -xJf "/tmp/${tarball}" -C /usr/local --strip-components=1 --no-same-owner \
      --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE' \
 && rm -f "/tmp/${tarball}" \
 && node --version && npm --version

# Install the integrity-locked CLI graph outside the runtime HOME volume. No
# dependency lifecycle scripts run. Claude's reviewed postinstall only places its
# native binary; link that locked Linux binary directly instead of running it.
COPY docker/cli/package.json docker/cli/package-lock.json docker/cli/.npmrc /opt/usage-clis/
RUN npm ci --prefix /opt/usage-clis --ignore-scripts --include=optional \
      --omit=dev --no-fund --no-audit \
 && case "${TARGETARCH:-amd64}" in \
      amd64) cli_arch=x64;   codex_target=x86_64-unknown-linux-musl ;; \
      arm64) cli_arch=arm64; codex_target=aarch64-unknown-linux-musl ;; \
      *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && claude_bin="/opt/usage-clis/node_modules/@anthropic-ai/claude-code-linux-${cli_arch}/claude" \
 && test -x "${claude_bin}" \
 && test -x "/opt/usage-clis/node_modules/@openai/codex-linux-${cli_arch}/vendor/${codex_target}/bin/codex" \
 && ln -s "${claude_bin}" /usr/local/bin/claude \
 && ln -s /opt/usage-clis/node_modules/.bin/codex /usr/local/bin/codex \
 && npm cache clean --force \
 && rm -rf /root/.npm

# Grok Build CLI: the official installer writes into $HOME/.grok, which would be
# hidden by the runtime volume, so fetch the same pinned release artifact the
# installer uses and install it into /opt/grok instead.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) grok_arch=x86_64;  grok_sha="${GROK_SHA256_AMD64}" ;; \
      arm64) grok_arch=aarch64; grok_sha="${GROK_SHA256_ARM64}" ;; \
      *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && artifact="grok-${GROK_VERSION}-linux-${grok_arch}.gz" \
 && curl --proto '=https' --proto-redir '=https' -fsSLo "/tmp/${artifact}" "https://x.ai/cli/${artifact}" \
 && echo "${grok_sha}  /tmp/${artifact}" | sha256sum -c - \
 && install -d -m 0755 /opt/grok/bin \
 && gzip -dc "/tmp/${artifact}" > /opt/grok/bin/grok \
 && chmod 0755 /opt/grok/bin/grok \
 && ln -s /opt/grok/bin/grok /usr/local/bin/grok \
 && rm -f "/tmp/${artifact}"

# This project, from the committed lockfile, without dev dependencies.
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY .python-version pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
 && /app/.venv/bin/usage --help >/dev/null

COPY docker/entrypoint.sh /usr/local/bin/usage-entrypoint
# Interactive `railway ssh` shells create private files by default (login state,
# config edits); the official CLIs still set their own credential-file modes.
RUN chmod 0755 /usr/local/bin/usage-entrypoint \
 && printf '\n# usage-api image: private files by default\numask 077\n' >> /etc/bash.bashrc

# Per-user state (CLI logins, cli-usage-api accounts.json/api_tokens.json) lives on
# the Railway volume. The self-updaters are disabled so the pinned versions stay
# what this image was built and verified with; rebuild to upgrade.
ENV HOME=/data/home \
    PATH=/app/.venv/bin:/opt/grok/bin:$PATH \
    DISABLE_AUTOUPDATER=1 \
    GROK_DISABLE_AUTOUPDATER=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

WORKDIR /data/home
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/usage-entrypoint"]
CMD ["sleep", "infinity"]
