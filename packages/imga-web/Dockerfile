# Multi-stage build for imga-web (Next.js 16 standalone output).
#
# - deps:    cached layer for npm install
# - builder: produces .next/standalone + .next/static
# - runner:  minimal node alpine that runs the standalone server
#
# Using node:22-alpine to match the local toolchain. node:22 is the
# active LTS as of Apr 2026 and Next.js 16 requires >= 20.9.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Sprint 9.0.6 E — typecheck-only stage. The test compose stack targets
# this stage so a CI run blocks on TS errors without paying for a full
# Next.js bundle. ``tsc --noEmit`` is what ``npm run typecheck`` already
# runs; we surface it as its own image so it can be invoked from
# anywhere a docker build is available.
FROM node:22-alpine AS typecheck
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run typecheck

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_API_URL is baked into the bundle at build time —
# Next.js inlines `process.env.NEXT_PUBLIC_*` references during
# `next build`. Production and staging therefore need separate
# image builds with different values for this arg.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Run as a non-root user.
RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# .next/standalone copies node_modules subset + server.js.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
