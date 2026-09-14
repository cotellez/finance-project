# CI showcase image for the finance CLI.
# Runtime-only: tests run in GitHub Actions, not in this image.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

ENTRYPOINT ["finance"]
CMD ["--help"]
