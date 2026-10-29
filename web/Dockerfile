# Front end for Railway: build with Node, serve dist/ with Caddy on $PORT.
FROM node:22.23.4-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS build
WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci --ignore-scripts --include=optional --no-audit --no-fund
COPY . .
# Public, non-secret default for the sign-in form. Never pass a token here.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# Retained for HTTP-only static serving (auto_https off; no HTTPS upstreams).
# Upstream 2.11.7 amd64 SBOM reports Go 1.26.8, not the eMudhra-fixed Go build.
# Audit/replace the image before adding TLS/ACME/proxying; see README.md.
FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
ENV PORT=8080
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
