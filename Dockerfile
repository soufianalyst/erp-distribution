FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY backend/ .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p static
COPY --from=frontend-build /app/dist static/
RUN chmod +x entrypoint.sh
EXPOSE 10000
CMD ["sh", "entrypoint.sh"]
