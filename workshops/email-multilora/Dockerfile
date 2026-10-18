FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY email_workshop ./email_workshop
RUN pip install --no-cache-dir ".[cloud]" \
    && useradd --uid 10001 --create-home workshop
USER workshop
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "email_workshop.cloud_api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "16"]
