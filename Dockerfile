# The registries are build arguments, not facts about one site. Defaults are upstream; a site
# that fronts them with a pull-through cache supplies its own:
#
#     docker build --build-arg PYTHON_IMAGE=<cache>/library/python:... .
#
# Digests are pinned and a pull-through cache preserves them, so the bytes are identical whichever
# registry serves them.
ARG PYTHON_IMAGE=docker.io/library/python:3.14.6-slim@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.12@sha256:73d2665b478d8fa2de1cf105c6841f8e9cb6b09e568fc7700440c09f8fcd7ac4

# A named stage rather than an inline `--mount=from=`, so the argument is expanded reliably.
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder

# Change the working directory to the `app` directory
WORKDIR /app

# Install dependencies
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable

# Copy the project into the intermediate image
COPY . /app

# Sync the project
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM ${PYTHON_IMAGE}

ENV USER=app
ENV GROUP=app

WORKDIR /app

# Copy the environment, but not the source code
COPY --from=builder --chown=app:app /app/.venv /app/.venv

RUN addgroup --gid 1001 --system "${GROUP}" && \
    adduser --no-create-home --shell /bin/false --disabled-password --uid 1001 --system --ingroup "${GROUP}" "${USER}"

USER $USER

EXPOSE 8080

ENTRYPOINT ["/app/.venv/bin/uvicorn",  "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
CMD ["app.main:get_app"]
