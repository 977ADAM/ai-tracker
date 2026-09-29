# The SvelteKit interface on adapter-node. The build stage compiles the app; the
# runtime stage keeps only the compiled server, which already bundles its own
# dependencies and therefore needs no `node_modules`.
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build


FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

WORKDIR /app
# The compiled server still imports the production dependencies of the app — the
# Markdown renderer of the reports — while adapter-node bundles its own. Nothing
# from the dev dependencies is needed at run time.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/build ./build

USER node
EXPOSE 3000

# Liveness only: the page itself needs the API, so any answer means the server
# is up, and the API has its own healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(() => process.exit(0)).catch(() => process.exit(1))"

CMD ["node", "build/index.js"]
