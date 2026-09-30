FROM node:22-alpine AS build

WORKDIR /app
ARG AI_TRACKER_BASE_PATH=/clustering/tracker
ENV AI_TRACKER_BASE_PATH=$AI_TRACKER_BASE_PATH
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build


FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3001

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/build ./build

USER node
EXPOSE 3001

CMD ["node", "build/index.js"]
