# Front end for Railway: build with Node, serve dist/ with Caddy on $PORT.
FROM node:22.20.0-bookworm-slim AS build
WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
# Public, non-secret default for the sign-in form. Never pass a token here.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM caddy:2.10.2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
ENV PORT=8080
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
