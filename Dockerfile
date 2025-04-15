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
    zlib1g-dev

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /requirements.txt

# --extra-index-url https://www.piwheels.org/simple  is for cryptography module to be prebuilt (or rustc etc needs to be installed)
RUN pip install --extra-index-url https://www.piwheels.org/simple  --target=/dependencies -r /requirements.txt

# Playwright is an alternative to Selenium
# Excluded this package from requirements.txt to prevent arm/v6 and arm/v7 builds from failing
# https://github.com/dgtlmoon/changedetection.io/pull/1067 also musl/alpine (not supported)
RUN pip install --target=/dependencies playwright~=1.48.0 \
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
# Starting wrapper
COPY changedetection.py /app/changedetection.py

# Github Action test purpose(test-only.yml).
# On production, it is effectively LOGGER_LEVEL=''.
ARG LOGGER_LEVEL=''
ENV LOGGER_LEVEL="$LOGGER_LEVEL"

WORKDIR /app
CMD ["python", "./changedetection.py", "-d", "/datastore"]


