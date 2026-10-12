# InsightSQL: the Streamlit app and (with another command) the refresh worker. See README.md, section 13.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata: lets TZ (for example TZ=Europe/London) set the clock the daily backup follows.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# A normal user runs the app; it may write only to /data (the data volume) and /backups.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin insightsql \
    && mkdir -p /data/uploads /backups \
    && chown -R insightsql:insightsql /data /backups

COPY . .

ENV INSIGHTSQL_DB_PATH=/data/insightsql.db \
    INSIGHTSQL_APP_DB_PATH=/data/app.db \
    INSIGHTSQL_DATASETS_DB_PATH=/data/datasets.db \
    INSIGHTSQL_UPLOADS_DIR=/data/uploads \
    INSIGHTSQL_BACKUP_DIR=/backups \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

USER insightsql
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"]

# Check the settings first: a misconfigured app stops here with a clear message.
CMD ["sh", "-c", "python scripts/preflight.py && exec streamlit run app.py"]
