# Multi-stage: build frontend, then package with Python backend.
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt
COPY backend/ .
COPY --from=frontend /build/dist static/
RUN chmod +x entrypoint.sh
EXPOSE 10000
CMD ["sh", "entrypoint.sh"]
