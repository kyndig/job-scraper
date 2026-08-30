FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

USER root
COPY pyproject.toml README.md ./
COPY job_scraper ./job_scraper
RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && chown -R pwuser:pwuser /app

USER pwuser

CMD ["python", "-m", "job_scraper.main"]
