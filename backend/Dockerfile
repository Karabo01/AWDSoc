FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl only, for container health probes. No compiler: every dependency ships
# a cp312 manylinux wheel, and build-essential cost 74 packages and ~350 MB to
# compile nothing. If pip ever needs to build from source it names the package,
# and that is the signal to reconsider - not a reason to ship a toolchain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

RUN useradd --system --uid 10001 awdsoc && chown -R awdsoc /app
USER awdsoc

EXPOSE 8000

# Role is selected by APP_ROLE, defaulting to api. See docker-entrypoint.sh
# for why this is an env var rather than a command override.
CMD ["docker-entrypoint.sh"]
