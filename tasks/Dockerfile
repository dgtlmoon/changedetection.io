# TicketWatch Dockerfile - Optimized for Fly.io
# Multi-stage build for minimal image size with Playwright browser support

ARG PYTHON_VERSION=3.11

# =============================================================================
# Stage 1: Builder - Install Python dependencies
# =============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Install build dependencies
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
    zlib1g-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Copy requirements files
COPY requirements.txt /requirements.txt
COPY tasks/requirements.txt /tasks-requirements.txt

# Configure pip cache and build settings
ENV PIP_CACHE_DIR=/tmp/pip-cache
ENV CRYPTOGRAPHY_DONT_BUILD_RUST=1

# Install main application dependencies
RUN --mount=type=cache,id=pip,sharing=locked,target=/tmp/pip-cache \
    pip install \
    --prefer-binary \
    --cache-dir=/tmp/pip-cache \
    --target=/dependencies \
    -r /requirements.txt

# Install TicketWatch-specific dependencies (PostgreSQL, etc.)
RUN --mount=type=cache,id=pip,sharing=locked,target=/tmp/pip-cache \
    pip install \
    --prefer-binary \
    --cache-dir=/tmp/pip-cache \
    --target=/dependencies \
    -r /tasks-requirements.txt

# Install Playwright with browsers
RUN --mount=type=cache,id=pip,sharing=locked,target=/tmp/pip-cache \
    pip install \
    --prefer-binary \
    --cache-dir=/tmp/pip-cache \
    --target=/dependencies \
    playwright~=1.56.0

# =============================================================================
# Stage 2: Final Image
# =============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/thetimechain/changedetection.io"
LABEL org.opencontainers.image.description="TicketWatch - Ticket monitoring powered by changedetection.io"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core runtime deps
    libxslt1.1 \
    zlib1g \
    # Locales for price formatting
    locales \
    # PDF processing
    poppler-utils \
    # File type detection
    file \
    # PostgreSQL client library
    libpq5 \
    # OpenCV dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    # Playwright browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libgtk-3-0 \
    # Fonts for rendering
    fonts-liberation \
    fonts-noto-color-emoji \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Configure locale
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Unbuffered Python output for proper logging
ENV PYTHONUNBUFFERED=1

# Configure Playwright browsers path
# This tells Playwright where to find/install browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Create necessary directories
RUN mkdir -p /datastore /ms-playwright /app

# Allow weak cipher suites for legacy site monitoring
RUN sed -i 's/^CipherString = .*/CipherString = DEFAULT@SECLEVEL=1/' /etc/ssl/openssl.cnf || true

# Copy Python dependencies from builder
COPY --from=builder /dependencies /usr/local
ENV PYTHONPATH=/usr/local

# Install Playwright browsers in final image
# We do this here to ensure the browser binaries are in the final image
RUN python -m playwright install chromium && python -m playwright install-deps chromium

# Copy application code
COPY changedetectionio /app/changedetectionio
COPY changedetection.py /app/changedetection.py

# Copy TicketWatch specific modules
COPY tasks/pg_store.py /app/tasks/pg_store.py

# Copy API docs
RUN mkdir -p /app/docs
COPY docs/api-spec.yaml /app/docs/api-spec.yaml

# Compile translation files
RUN pybabel compile -d /app/changedetectionio/translations || true

# Expose port (Fly.io default)
EXPOSE 5000

# Set working directory
WORKDIR /app

# Health check for Fly.io
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')" || exit 1

# Environment defaults for Fly.io
ENV PORT=5000
ENV LISTEN_HOST=0.0.0.0
ENV FETCH_WORKERS=5

# Start the application with gunicorn for production deployment
# Using gevent worker for async support with Socket.IO
# Note: The app must be started through changedetection.py to initialize the datastore
CMD ["sh", "-c", "sleep 2 && python ./changedetection.py -d /datastore -p 5000 -h 0.0.0.0"]
