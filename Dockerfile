# pip dependencies install stage

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# See `cryptography` pin comment in requirements.txt
ARG CRYPTOGRAPHY_DONT_BUILD_RUST=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    gcc \
    libc-dev \
    libffi-dev \
    libjpeg-dev \
    libssl-dev \
    libxslt-dev \
    make \
    patch \
    zlib1g-dev

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /requirements.txt

# Use cache mounts and multiple wheel sources for faster ARM builds
ENV PIP_CACHE_DIR=/tmp/pip-cache
RUN --mount=type=cache,target=/tmp/pip-cache \
    pip install \
    --extra-index-url https://www.piwheels.org/simple \
    --extra-index-url https://pypi.anaconda.org/ARM-software/simple \
    --cache-dir=/tmp/pip-cache \
    --target=/dependencies \
    -r /requirements.txt

# Playwright is an alternative to Selenium
# Excluded this package from requirements.txt to prevent arm/v6 and arm/v7 builds from failing
# https://github.com/dgtlmoon/changedetection.io/pull/1067 also musl/alpine (not supported)
RUN --mount=type=cache,target=/tmp/pip-cache \
    pip install \
    --cache-dir=/tmp/pip-cache \
    --target=/dependencies \
    playwright~=1.48.0 \
    || echo "WARN: Failed to install Playwright. The application can still run, but the Playwright option will be disabled."

# Final image stage
FROM python:${PYTHON_VERSION}-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/dgtlmoon/changedetection.io"

RUN set -ex; \
    apt-get update && apt-get install -y --no-install-recommends \
        gosu \
        libxslt1.1 \
        # For presenting price amounts correctly in the restock/price detection overview
        locales \
        # For pdftohtml
        poppler-utils \
        zlib1g && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*; \
    useradd -u 911 -U -m -s /bin/false changedetection && \
    usermod -G users changedetection; \
    mkdir -p /datastore

# Re #80, sets SECLEVEL=1 in openssl.conf to allow monitoring sites with weak/old cipher suites
RUN sed -i 's/^CipherString = .*/CipherString = DEFAULT@SECLEVEL=1/' /etc/ssl/openssl.cnf

# Copy modules over to the final image and add their dir to PYTHONPATH
COPY --from=builder /dependencies /usr/local
ENV PYTHONPATH=/usr/local \
    # https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
    PYTHONUNBUFFERED=1 \
    # https://stackoverflow.com/questions/64808915/should-pycache-folders-be-included-in-production-containers
    # This avoids permission denied errors because the app directory is root-owned.
    PYTHONDONTWRITEBYTECODE=1 \
    DATASTORE_PATH="/datastore" \
    # Disable creation of Pytest cache dir when running tests inside the container by default
    PYTEST_ADDOPTS="-p no:cacheprovider"

EXPOSE 5000

# The entrypoint script handling PUID/PGID and permissions
COPY --chmod=755 docker-entrypoint.sh /app/docker-entrypoint.sh

# The actual flask app module
COPY changedetectionio /app/changedetectionio
# Starting wrapper
COPY changedetection.py /app/changedetection.py

# create test directory for pytest to run in
RUN mkdir -p /app/changedetectionio/test-datastore && \
    chown changedetection:changedetection /app/changedetectionio/test-datastore

# Github Action test purpose(test-only.yml).
# On production, it is effectively LOGGER_LEVEL=''.
ARG LOGGER_LEVEL=''
ENV LOGGER_LEVEL="$LOGGER_LEVEL"

WORKDIR /app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "/app/changedetection.py"]
