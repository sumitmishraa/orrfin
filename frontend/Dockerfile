# Web app image (BUILD_PLAN §3 Hosting, Step 28). Build from frontend/:
#   docker build -t orrfin-web frontend
# The browser calls /api/* on this server; Next forwards it to the API container (next.config.ts).
FROM node:22-slim AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The /api rewrite target is fixed at build time, so the API's address inside Docker is baked in here.
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
RUN npm run build && npm prune --omit=dev

FROM node:22-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
COPY --from=build --chown=node:node /web ./
USER node
EXPOSE 3000
CMD ["npm", "start"]
