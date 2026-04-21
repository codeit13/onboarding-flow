# ---- Base image ----
    FROM node:21-alpine AS base

    # Install pnpm globally
    RUN corepack enable && corepack prepare pnpm@latest --activate
    
    WORKDIR /app
    
    # ---- Dependencies ----
    FROM base AS deps
    
    # Install build dependencies
    RUN apk add --no-cache libc6-compat python3 make g++
    
    # Copy only package manager files
    COPY package.json pnpm-lock.yaml ./
    
    # Install dependencies (with frozen lockfile for reproducibility)
    RUN pnpm install --frozen-lockfile
    
    # ---- Builder ----
    FROM base AS builder
    
    WORKDIR /app
    
    # Copy installed dependencies
    COPY --from=deps /app/node_modules ./node_modules
    COPY --from=deps /app/pnpm-lock.yaml ./pnpm-lock.yaml
    
    # Copy the rest of the source code
    COPY . .
    
    # Build the app
    ENV NEXT_TELEMETRY_DISABLED 1
    ENV CONTAINER_MODE=true
    RUN pnpm build
    
    # ---- Production ----
    FROM base AS runner
    
    WORKDIR /app
    
    ENV NODE_ENV production
    ENV NEXT_TELEMETRY_DISABLED 1
    
    RUN addgroup --system --gid 1001 nodejs
    RUN adduser --system --uid 1001 nextjs
    
    # Copy static assets and build output
    COPY --from=builder /app/public ./public
    COPY --from=builder /app/.next/standalone ./
    COPY --from=builder /app/.next/static ./.next/static
    
    USER nextjs
    
    EXPOSE 3000
    ENV PORT 3000
    ENV HOSTNAME "0.0.0.0"
    
    CMD ["node", "server.js"]
