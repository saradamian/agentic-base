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

# The version is read from git, as the release workflow reads it, so the image says which build it
# is whatever the pipeline passes. git is installed in this stage only; the final image copies the
# environment and nothing else. VERSION overrides it when a pipeline has a better answer, such as a
# shallow clone with no tags.
ARG VERSION=""
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git >/dev/null \
    && rm -rf /var/lib/apt/lists/*

# Change the working directory to the `app` directory
WORKDIR /app

# Install dependencies
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev --extra service --extra provenance

# Copy the project into the intermediate image
COPY . /app

# Sync the project
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -n "${VERSION}" ]; then export SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}"; fi \
    && uv sync --frozen --no-editable --no-dev --extra service --extra provenance

FROM ${PYTHON_IMAGE}

ENV USER=app
ENV GROUP=app

WORKDIR /app

# Copy the environment, but not the source code
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# The same uid and gid the chart runs the pod as.
RUN addgroup --gid 1000 --system "${GROUP}" && \
    adduser --no-create-home --shell /bin/false --disabled-password --uid 1000 --system --ingroup "${GROUP}" "${USER}"

USER $USER

EXPOSE 8080

ENTRYPOINT ["/app/.venv/bin/uvicorn",  "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
CMD ["agentic_base.main:get_app"]
