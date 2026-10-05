FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG API_INTERNAL_URL=http://127.0.0.1:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S setu && adduser -S setu -G setu
COPY --chown=setu:setu --from=build /app/.next ./.next
COPY --chown=setu:setu --from=build /app/package.json ./package.json
COPY --chown=setu:setu --from=build /app/next.config.ts ./next.config.ts
COPY --chown=setu:setu --from=build /app/i18n ./i18n
COPY --chown=setu:setu --from=build /app/public ./public
COPY --chown=setu:setu --from=deps /app/node_modules ./node_modules
USER setu
EXPOSE 3000
CMD ["npm", "start"]
