# syntax=docker/dockerfile:1
#
# Railway / container image for the read-only usage API backend.
#
# The image installs Python, this project, Node.js and the three first-party CLIs,
# then idles with `sleep infinity`. Log in to the CLIs, configure accounts and start
# `usage api serve` manually through `railway ssh` (see docs/deploy-railway.md).
# No credential, token or login state is baked into the image: everything per-user
# lives under HOME=/data/home on the Railway volume mounted at /data at runtime.
#
# Pinned versions (update deliberately; record the source when changing them):
#   uv           0.13.5    ghcr.io/astral-sh/uv (matches the uv that wrote uv.lock)
#   Node.js      22.23.4   LTS "Jod", https://nodejs.org/dist/v22.23.4/SHASUMS256.txt
#   Claude Code  2.1.308   npm @anthropic-ai/claude-code (npm "stable" dist-tag)
#   Codex CLI    0.165.0   npm @openai/codex ("latest" dist-tag)
#   Grok Build   1.0.70    https://x.ai/cli/stable ; artifacts named by
#                          https://x.ai/cli/install.sh (grok-<ver>-linux-<arch>.gz).
#                          xAI publishes no checksums; the SHA-256 values below were
#                          computed from the downloaded artifacts on 2026-10-29
#                          (trust on first use), so a changed artifact fails the build.

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.12-slim-bookworm

ARG TARGETARCH
ARG NODE_VERSION=22.23.4
ARG NODE_SHA256_AMD64=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
ARG NODE_SHA256_ARM64=6287aa46b6c375d816e63ae66d024fbbfd70404825aabdfdf898a970871d2f4b
ARG CLAUDE_CODE_VERSION=2.1.308
ARG CODEX_VERSION=0.165.0
ARG GROK_VERSION=1.0.70
ARG GROK_SHA256_AMD64=11d27a30adfb75c4b9b180072ab27412a1916f054ff5497ab70fb9a77d304bcc
ARG GROK_SHA256_ARM64=0d9e47fc2cb14db2f52f99e9289c41b3723b64de05c284a9f18c2e8df52550cf

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git tmux procps less tini xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node.js (official tarball, checksum-verified) for the npm-distributed CLIs.
RUN case "${TARGETARCH:-amd64}" in \
      amd64) node_arch=x64;   node_sha="${NODE_SHA256_AMD64}" ;; \
      arm64) node_arch=arm64; node_sha="${NODE_SHA256_ARM64}" ;; \
      *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && tarball="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" \
 && curl -fsSLo "/tmp/${tarball}" "https://nodejs.org/dist/v${NODE_VERSION}/${tarball}" \
 && echo "${node_sha}  /tmp/${tarball}" | sha256sum -c - \
 && tar -xJf "/tmp/${tarball}" -C /usr/local --strip-components=1 --no-same-owner \
      --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE' \
 && rm -f "/tmp/${tarball}" \
 && node --version && npm --version

# Claude Code and Codex CLI, globally under /usr/local (outside the runtime HOME
# volume, so the mounted volume cannot hide them).
RUN npm install -g --no-fund --no-audit \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@openai/codex@${CODEX_VERSION}" \
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
 && curl -fsSLo "/tmp/${artifact}" "https://x.ai/cli/${artifact}" \
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
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
 && /app/.venv/bin/usage --help >/dev/null

COPY docker/entrypoint.sh /usr/local/bin/usage-entrypoint
# Interactive `railway ssh` shells create private files by default (login state,
# config edits); the official CLIs still set their own credential-file modes.
RUN chmod 0755 /usr/local/bin/usage-entrypoint \
 && printf '\n# usage-api image: private files by default\numask 077\n' >> /etc/bash.bashrc

# Per-user state (CLI logins, usage-tui accounts.json/api_tokens.json) lives on
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
