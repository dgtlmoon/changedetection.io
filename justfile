# Default recipe - show available commands
default:
    @just --list

# Build the test image
build:
    docker compose -f docker-compose.override.test.yml build changedetection

# Start test services (selenium, sockpuppetbrowser, etc.)
up:
    docker compose  -f docker-compose.override.test.yml up --build -d

# Stop and remove test services
down:
    docker compose -f docker-compose.override.test.yml down --volumes

# Run unit tests
unittest +tests="": build
    docker run --rm test-changedetectionio bash -c 'python3 -m unittest {{tests}}'

# Run tests with Playwright
test-playwright test_path="": up
    docker run --rm --name "changedet-playwright-test" --network changedetectionio-test-network --network-alias changedet -e "FLASK_SERVER_NAME=changedet" -e "PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000" test-changedetectionio bash -c 'cd changedetectionio && pytest --live-server-port=5004 --live-server-host=0.0.0.0 {{test_path}}'

