# Minimal, offline test sandbox for RepoPilot AI.
# It contains Python + pytest only. The container is started with --network none, a read-only root FS,
# all capabilities dropped and an unprivileged uid (see backend/app/services/validation_service.py).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir "pytest>=8,<9"

WORKDIR /work
# No ENTRYPOINT/CMD on purpose: the backend supplies a fixed, allowlisted command.
