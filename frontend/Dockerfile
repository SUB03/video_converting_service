FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Nitro bakes the /api proxy target into the server bundle at build time
ARG API_URL=http://video_converter:8000
ENV API_URL=${API_URL}
RUN npm run build


FROM node:24-alpine

WORKDIR /app

# .output is self-contained: no node_modules needed at runtime
COPY --from=build /app/.output ./.output

ENV HOST=0.0.0.0 \
    PORT=3000 \
    NODE_ENV=production

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
