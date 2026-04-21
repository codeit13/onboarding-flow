# ============================================================
# Axis Hiring Agent — ACS Frontend (Next.js)
# ============================================================

# ---- Stage 1: Install dependencies ----
FROM node:20-alpine AS deps

WORKDIR /app

# Install libc compat for Alpine
RUN apk add --no-cache libc6-compat

COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# ---- Stage 2: Build ----
FROM node:20-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Copy deps
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build accepts NEXT_PUBLIC_ vars at build time via ARG
ARG NEXT_PUBLIC_API_BASE=http://acs-backend:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN npm run build

# ---- Stage 3: Production runner ----
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Copy build output
COPY --from=builder /app/.next        ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["npm", "start"]
