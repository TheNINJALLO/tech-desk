FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KTD_CONFIG=/app/config.yaml

WORKDIR /app

RUN useradd --create-home --uid 10001 techdesk
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data/evidence /app/data/transcripts /app/data/backups /app/logs \
    && chown -R techdesk:techdesk /app

USER techdesk
CMD ["python", "-m", "kingdom_tech_desk"]
