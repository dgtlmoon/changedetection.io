# pip dependencies install stage

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# See `cryptography` pin comment in requirements.txt

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
    pkg-config \
    zlib1g-dev

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /requirements.txt

# Use cache mounts and multiple wheel sources for faster ARM builds
ENV PIP_CACHE_DIR=/tmp/pip-cache
# Help Rust find OpenSSL for cryptography package compilation on ARM
ENV PKG_CONFIG_PATH="/usr/lib/pkgconfig:/usr/lib/arm-linux-gnueabihf/pkgconfig:/usr/lib/aarch64-linux-gnu/pkgconfig"
ENV PKG_CONFIG_ALLOW_SYSTEM_CFLAGS=1
ENV OPENSSL_DIR="/usr"
ENV OPENSSL_LIB_DIR="/usr/lib/arm-linux-gnueabihf"
ENV OPENSSL_INCLUDE_DIR="/usr/include/openssl"
# Additional environment variables for cryptography Rust build
# This will REPLACE the default pypi.org index.
# For security reasons (to prevent dependency confusion attacks), --extra-index-url is not used.
# Your custom index must contain all required packages and their dependencies.
# Using a private repository manager that proxies pypi.org is recommended.
ARG PIP_INDEX_URL
# hadolint ignore=DL3013
RUN if [ -n "$PIP_INDEX_URL" ] ; then \
    echo "Using custom python package index: $PIP_INDEX_URL" ; \
    pip3 install --no-cache-dir --upgrade --index-url $PIP_INDEX_URL -r requirements.txt ; \
else \
    pip3 install --no-cache-dir --upgrade -r requirements.txt ; \
fi


# Playwright is an alternative to Selenium
# Excluded this package from requirements.txt to prevent arm/v6 and arm/v7 builds from failing
# https://github.com/dgtlmoon/changedetection.io/pull/1067 also musl/alpine (not supported)
RUN --mount=type=cache,id=pip,sharing=locked,target=/tmp/pip-cache \
  pip install \
  --prefer-binary \
  --cache-dir=/tmp/pip-cache \
  --target=/dependencies \
  playwright~=1.48.0 \
  || echo "WARN: Failed to install Playwright. The application can still run, but the Playwright option will be disabled."


# Final image stage
FROM python:${PYTHON_VERSION}-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/dgtlmoon/changedetection.io"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxslt1.1 \
    # For presenting price amounts correctly in the restock/price detection overview
    locales \
    # For pdftohtml
    poppler-utils \
    # favicon type detection and other uses
    file \
    zlib1g \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

RUN [ ! -d "/datastore" ] && mkdir /datastore

# Re #80, sets SECLEVEL=1 in openssl.conf to allow monitoring sites with weak/old cipher suites
RUN sed -i 's/^CipherString = .*/CipherString = DEFAULT@SECLEVEL=1/' /etc/ssl/openssl.cnf

# Copy modules over to the final image and add their dir to PYTHONPATH
COPY --from=builder /dependencies /usr/local
ENV PYTHONPATH=/usr/local

EXPOSE 5000

# The actual flask app module
COPY changedetectionio /app/changedetectionio

# Also for OpenAPI validation wrapper - needs the YML
RUN [ ! -d "/app/docs" ] && mkdir /app/docs
COPY docs/api-spec.yaml /app/docs/api-spec.yaml

# Starting wrapper
COPY changedetection.py /app/changedetection.py

# Github Action test purpose(test-only.yml).
# On production, it is effectively LOGGER_LEVEL=''.
ARG LOGGER_LEVEL=''
ENV LOGGER_LEVEL="$LOGGER_LEVEL"

# Default
ENV LC_ALL=en_US.UTF-8

WORKDIR /app
CMD ["python", "./changedetection.py", "-d", "/datastore"]


