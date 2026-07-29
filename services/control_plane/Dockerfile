FROM node:22-bookworm-slim

ENV NODE_ENV=production
WORKDIR /app

COPY package.json .npmrc ./
RUN npm install --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force

COPY src ./src
COPY scripts ./scripts

RUN mkdir -p /var/lib/amosclaud/repositories /var/lib/amosclaud/skills \
    && chown -R node:node /app /var/lib/amosclaud

USER node
EXPOSE 8300
CMD ["npm", "start"]
