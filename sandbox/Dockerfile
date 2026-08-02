FROM node:20-bookworm-slim AS node-runtime

FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app

COPY vite-runtime/package.json vite-runtime/package-lock.json /opt/gameweave-vite/
RUN npm ci --prefix /opt/gameweave-vite --no-audit --no-fund
COPY vite-runtime/vite.config.mjs /opt/gameweave-vite/vite.config.mjs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER pwuser

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
