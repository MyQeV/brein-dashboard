FROM node:26-alpine AS deps
WORKDIR /app
# node:25+ dropped bundled corepack; install the version package.json pins.
RUN npm install -g pnpm@10.33.4
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:26-alpine AS builder
WORKDIR /app
RUN npm install -g pnpm@10.33.4
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next serializes rewrites into the build manifest, so the API origin the
# browser is proxied to is fixed at build time — unlike server-side fetches,
# which read the env var per request. It has to be supplied here.
ARG BREIN_API_ORIGIN=http://brein:8001
ENV BREIN_API_ORIGIN=$BREIN_API_ORIGIN
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm run build

FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Don't run as root.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
