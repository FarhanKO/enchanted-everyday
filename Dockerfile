# One image for the worker, the bot and the migrate job.
FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# deps layer first, so code changes don't reinstall everything
COPY pyproject.toml README.md ./
RUN mkdir -p engine bot && touch engine/__init__.py bot/__init__.py \
    && pip install . \
    && pip uninstall -y content-engine

COPY engine ./engine
COPY bot ./bot
COPY templates ./templates
RUN pip install --no-deps .

USER app
CMD ["engine", "serve"]
