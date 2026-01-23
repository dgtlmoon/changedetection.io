#!/bin/bash
# Test script for CLI options - Parallel execution
# Tests -u, -uN, -r, -b flags

set -u  # Exit on undefined variables

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test results directory (for parallel safety)
TEST_RESULTS_DIR="/tmp/cli-test-results-$$"
mkdir -p "$TEST_RESULTS_DIR"

# Cleanup function
cleanup() {
    echo ""
    echo "=== Cleaning up test directories ==="
    rm -rf /tmp/cli-test-* 2>/dev/null || true
    rm -rf "$TEST_RESULTS_DIR" 2>/dev/null || true
    # Kill any hanging processes
    pkill -f "changedetection.py.*cli-test" 2>/dev/null || true
}
trap cleanup EXIT

# Helper to record test result
record_result() {
    local test_num=$1
    local status=$2  # pass or fail
    local message=$3

    echo "$status|$message" > "$TEST_RESULTS_DIR/test_${test_num}.result"
}

# Run a test in background
run_test() {
    local test_num=$1
    local test_name=$2
    local test_func=$3

    (
        echo -e "${YELLOW}[Test $test_num]${NC} $test_name"
        if $test_func "$test_num"; then
            record_result "$test_num" "pass" "$test_name"
            echo -e "${GREEN}✓ PASS${NC}: $test_name"
        else
            record_result "$test_num" "fail" "$test_name"
            echo -e "${RED}✗ FAIL${NC}: $test_name"
        fi
    ) &
}

# =============================================================================
# Test Functions (each runs independently)
# =============================================================================

test_help_flag() {
    local test_id=$1
    timeout 3 python3 changedetection.py --help 2>&1 | grep -q "Add URLs on startup"
}

test_version_flag() {
    local test_id=$1
    timeout 3 python3 changedetection.py --version 2>&1 | grep -qE "changedetection.io [0-9]+\.[0-9]+"
}

test_single_url() {
    local test_id=$1
    local dir="/tmp/cli-test-single-${test_id}-$$"
    timeout 10 python3 changedetection.py -d "$dir" -C -u https://example.com -b &>/dev/null
    [ -f "$dir/url-watches.json" ] && \
    [ "$(python3 -c "import json; print(len(json.load(open('$dir/url-watches.json')).get('watching', {})))")" -eq 1 ]
}

test_multiple_urls() {
    local test_id=$1
    local dir="/tmp/cli-test-multi-${test_id}-$$"
    timeout 12 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -u https://github.com \
        -u https://httpbin.org \
        -b &>/dev/null
    [ -f "$dir/url-watches.json" ] && \
    [ "$(python3 -c "import json; print(len(json.load(open('$dir/url-watches.json')).get('watching', {})))")" -eq 3 ]
}

test_url_with_options() {
    local test_id=$1
    local dir="/tmp/cli-test-opts-${test_id}-$$"
    timeout 10 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -u0 '{"title":"Test Site","processor":"text_json_diff"}' \
        -b &>/dev/null
    [ -f "$dir/url-watches.json" ] && \
    python3 -c "import json; data=json.load(open('$dir/url-watches.json')); watches=data.get('watching', {}); exit(0 if any(w.get('title')=='Test Site' for w in watches.values()) else 1)"
}

test_multiple_urls_with_options() {
    local test_id=$1
    local dir="/tmp/cli-test-multi-opts-${test_id}-$$"
    timeout 12 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -u0 '{"title":"Site One"}' \
        -u https://github.com \
        -u1 '{"title":"Site Two"}' \
        -b &>/dev/null
    [ -f "$dir/url-watches.json" ] && \
    [ "$(python3 -c "import json; print(len(json.load(open('$dir/url-watches.json')).get('watching', {})))")" -eq 2 ] && \
    python3 -c "import json; data=json.load(open('$dir/url-watches.json')); watches=data.get('watching', {}); titles=[w.get('title') for w in watches.values()]; exit(0 if 'Site One' in titles and 'Site Two' in titles else 1)"
}

test_batch_mode_exit() {
    local test_id=$1
    local dir="/tmp/cli-test-batch-${test_id}-$$"
    local start=$(date +%s)
    timeout 15 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -b &>/dev/null
    local end=$(date +%s)
    local elapsed=$((end - start))
    [ $elapsed -lt 14 ]
}

test_recheck_all() {
    local test_id=$1
    local dir="/tmp/cli-test-recheck-all-${test_id}-$$"
    mkdir -p "$dir"
    cat > "$dir/url-watches.json" << 'EOF'
{"watching":{"test-uuid":{"url":"https://example.com","last_checked":0,"processor":"text_json_diff","uuid":"test-uuid"}},"settings":{"application":{"password":false}}}
EOF
    timeout 10 python3 changedetection.py -d "$dir" -r all -b 2>&1 | grep -q "Queuing all"
}

test_recheck_specific() {
    local test_id=$1
    local dir="/tmp/cli-test-recheck-uuid-${test_id}-$$"
    mkdir -p "$dir"
    cat > "$dir/url-watches.json" << 'EOF'
{"watching":{"uuid-1":{"url":"https://example.com","last_checked":0,"processor":"text_json_diff","uuid":"uuid-1"},"uuid-2":{"url":"https://github.com","last_checked":0,"processor":"text_json_diff","uuid":"uuid-2"}},"settings":{"application":{"password":false}}}
EOF
    timeout 10 python3 changedetection.py -d "$dir" -r uuid-1,uuid-2 -b 2>&1 | grep -q "Queuing 2 specific watches"
}

test_combined_operations() {
    local test_id=$1
    local dir="/tmp/cli-test-combined-${test_id}-$$"
    timeout 12 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -u https://github.com \
        -r all \
        -b &>/dev/null
    [ -f "$dir/url-watches.json" ] && \
    [ "$(python3 -c "import json; print(len(json.load(open('$dir/url-watches.json')).get('watching', {})))")" -eq 2 ]
}

test_invalid_json() {
    local test_id=$1
    local dir="/tmp/cli-test-invalid-${test_id}-$$"
    timeout 5 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -u0 'invalid json here' \
        2>&1 | grep -qi "invalid json\|json decode error"
}

test_create_directory() {
    local test_id=$1
    local dir="/tmp/cli-test-create-${test_id}-$$/nested/path"
    timeout 10 python3 changedetection.py -d "$dir" -C \
        -u https://example.com \
        -b &>/dev/null
    [ -d "$dir" ]
}

# =============================================================================
# Main Test Execution
# =============================================================================

echo "=========================================="
echo "  CLI Options Test Suite (Parallel)"
echo "=========================================="
echo ""

# Launch all tests in parallel
run_test 1 "Help flag (--help) shows usage without initialization" test_help_flag
run_test 2 "Version flag (--version) displays version" test_version_flag
run_test 3 "Add single URL with -u flag" test_single_url
run_test 4 "Add multiple URLs with multiple -u flags" test_multiple_urls
run_test 5 "Add URL with JSON options using -u0" test_url_with_options
run_test 6 "Add multiple URLs with different options (-u0, -u1)" test_multiple_urls_with_options
run_test 7 "Batch mode (-b) exits automatically after processing" test_batch_mode_exit
run_test 8 "Recheck all watches with -r all" test_recheck_all
run_test 9 "Recheck specific watches with -r UUID" test_recheck_specific
run_test 10 "Combined: Add URLs and recheck all with -u and -r all" test_combined_operations
run_test 11 "Invalid JSON in -u0 option should show error" test_invalid_json
run_test 12 "Create datastore directory with -C flag" test_create_directory

# Wait for all tests to complete
echo ""
echo "Waiting for all tests to complete..."
wait

# Collect results
echo ""
echo "=========================================="
echo "  Test Summary"
echo "=========================================="

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

for result_file in "$TEST_RESULTS_DIR"/test_*.result; do
    if [ -f "$result_file" ]; then
        TESTS_RUN=$((TESTS_RUN + 1))
        status=$(cut -d'|' -f1 < "$result_file")
        if [ "$status" = "pass" ]; then
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    fi
done

echo "Tests run:    $TESTS_RUN"
echo -e "${GREEN}Tests passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Tests failed: $TESTS_FAILED${NC}"
else
    echo -e "${GREEN}Tests failed: $TESTS_FAILED${NC}"
fi
echo "=========================================="
echo ""

# Exit with appropriate code
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
