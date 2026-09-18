# CI showcase image for the finance CLI.
# Runtime-only: tests run in GitHub Actions, not in this image.
#
# Base pin (Module 4, researcher finding #3): floating `3.12-slim` tags are a
# supply-chain risk. Pinned to the linux/amd64 digest pushed 2026-09-01.
# Refresh via Dependabot/Renovate digest bumps — deferred trigger: first
# external security audit or compliance requirement for CVE patch velocity.
FROM python:3.12-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Layer-order note: `pip install .` needs the full source tree, so a separate
# deps-first layer is not applicable at this scale. Metadata is still copied
# before source for maximal cache reuse on src-only changes.
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Non-root runtime (Module 4, researcher finding #2): the CLI writes local
# state (*.db / *.json) into the workdir, so the runtime user must own /app
# or execution crashes with Permission Denied.
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --shell /usr/sbin/nologin apprunner \
    && chown -R 10001:10001 /app

USER 10001:10001

# No HEALTHCHECK by design: this is an exit-0 CLI, not a long-running
# service. Exit codes are the health contract (researcher finding #6).
ENTRYPOINT ["finance"]
CMD ["--help"]
