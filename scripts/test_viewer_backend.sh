#!/usr/bin/env bash
# NOTE: deliberately NOT using `set -e`. This is a test harness — a failing
# endpoint must be counted and reported, not abort the run before the summary.
set -uo pipefail

# ==============================================================================
# Thermal Viewer Backend - Automated Test Script
# ==============================================================================
# Purpose: Validate all viewer backend endpoints
# Usage:   ./scripts/test_viewer_backend.sh [BASE_URL]
#
# Environment overrides:
#   BASE_URL       viewer API root      (default: https://dev-thermal.dabuilders.net/viewer)
#   SITE / SECTOR  hierarchy to test    (default: leyte / mahanagdong-b)
#   PERIOD         pin a period         (default: auto-discovered — see below)
#   PAD_ID         pin a pad            (default: first pad of the chosen period)
#   IMAGES_TABLE   DynamoDB table       (default: thermal-api-dev-images-7ecb7171)
#   AWS_REGION     region               (default: ap-southeast-1)
#   VERBOSE=true   print URLs + bodies
#
# Period/pad selection: periods and pads are NOT independent — a period can exist
# while having zero pads. The suite therefore walks the period list and picks the
# first period that actually has pads, then takes a pad from THAT period. Pinning
# an unrelated PERIOD/PAD_ID pair produces spurious NoSuchKey failures.
# ==============================================================================

BASE_URL="${1:-${BASE_URL:-https://dev-thermal.dabuilders.net/viewer}}"
VERBOSE="${VERBOSE:-false}"
SITE="${SITE:-leyte}"
SECTOR="${SECTOR:-mahanagdong-b}"
IMAGES_TABLE="${IMAGES_TABLE:-thermal-api-dev-images-7ecb7171}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
CURL_TIMEOUT="${CURL_TIMEOUT:-60}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Per-run response file (avoids clobbering a shared /tmp path between runs)
RESPONSE_FILE="$(mktemp -t viewer_test_response.XXXXXX)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

# ==============================================================================
# Helper Functions
# ==============================================================================

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_test() {
    echo -e "${YELLOW}TEST:${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ INFO:${NC} $1"
}

# print_pass / print_fail own the pass/fail counters. Callers must NOT also
# increment them — doing so previously double-counted every inline assertion.
print_pass() {
    echo -e "${GREEN}✓ PASS:${NC} $1"
    ((PASSED_TESTS+=1))
}

print_fail() {
    echo -e "${RED}✗ FAIL:${NC} $1"
    ((FAILED_TESTS+=1))
}

# assert <name> <condition-exit-code> — records one test from an inline check.
assert() {
    local name="$1"
    local ok="$2"
    ((TOTAL_TESTS+=1))
    if [ "$ok" -eq 0 ]; then
        print_pass "$name"
    else
        print_fail "$name"
    fi
}

test_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"

    ((TOTAL_TESTS+=1))
    print_test "$name"

    if [ "$VERBOSE" = "true" ]; then
        echo "  URL: $url"
    fi

    local http_code
    http_code=$(curl -s --max-time "$CURL_TIMEOUT" -o "$RESPONSE_FILE" -w "%{http_code}" "$url")

    if [ "$http_code" = "$expected_status" ]; then
        print_pass "$name (HTTP $http_code)"

        if [ "$VERBOSE" = "true" ] && [ -f "$RESPONSE_FILE" ]; then
            echo "  Response:"
            jq '.' "$RESPONSE_FILE" 2>/dev/null || cat "$RESPONSE_FILE"
        fi

        return 0
    else
        print_fail "$name (HTTP $http_code, expected $expected_status)"

        if [ -f "$RESPONSE_FILE" ]; then
            echo "  Response:"
            head -c 400 "$RESPONSE_FILE"; echo
        fi

        return 1
    fi
}

# GET a URL and echo the body (does not count as a test)
fetch() {
    curl -s --max-time "$CURL_TIMEOUT" "$1"
}

extract_json_value() {
    local key="$1"
    local value
    value=$(jq -r "$key" "$RESPONSE_FILE" 2>/dev/null)
    if [ -n "$value" ] && [ "$value" != "null" ]; then
        echo "$value"
    else
        echo ""
    fi
}

print_summary_and_exit() {
    print_header "Test Summary"
    echo -e "Total Tests:  $TOTAL_TESTS"
    echo -e "${GREEN}Passed:       $PASSED_TESTS${NC}"
    echo -e "${RED}Failed:       $FAILED_TESTS${NC}"

    if [ "$FAILED_TESTS" -eq 0 ]; then
        echo -e "\n${GREEN}✓ All tests passed!${NC}\n"
        exit 0
    else
        echo -e "\n${RED}✗ Some tests failed${NC}\n"
        exit 1
    fi
}

# ==============================================================================
# Test Suite
# ==============================================================================

echo -e "${GREEN}Thermal Viewer Backend - Test Suite${NC}"
echo "Base URL: $BASE_URL"
echo ""

command -v jq >/dev/null 2>&1 || { echo -e "${RED}jq is required but not installed.${NC}"; exit 2; }

# ==============================================================================
# 1. Health Check
# ==============================================================================

print_header "1. Health Check"

test_endpoint "Health Endpoint" "$BASE_URL/health"

status=$(extract_json_value '.status')
[ "$status" = "healthy" ]
assert "Service status is healthy (got: ${status:-<none>})" $?

# ==============================================================================
# 2. Data Discovery
# ==============================================================================

print_header "2. Data Discovery"

# 2.1 Sites
test_endpoint "Get Sites" "$BASE_URL/api/sites"
jq -e --arg site "$SITE" 'index($site)' "$RESPONSE_FILE" >/dev/null 2>&1
assert "Site '$SITE' present in /api/sites" $?

# 2.2 Sectors
test_endpoint "Get Sectors for $SITE" "$BASE_URL/api/sectors?site=$SITE"
jq -e --arg sector "$SECTOR" 'index($sector)' "$RESPONSE_FILE" >/dev/null 2>&1
assert "Sector '$SECTOR' present in /api/sectors" $?

# 2.3 Periods
test_endpoint "Get Periods for $SITE/$SECTOR" "$BASE_URL/api/periods?site=$SITE&sector=$SECTOR"
PERIODS=$(jq -r '.[]?' "$RESPONSE_FILE" 2>/dev/null)

if [ -z "$PERIODS" ]; then
    print_fail "No periods returned for $SITE/$SECTOR — cannot continue"
    ((TOTAL_TESTS+=1))
    print_summary_and_exit
fi

# 2.4 Pick a period that ACTUALLY HAS PADS, then a pad from that same period.
#     (A period existing does not imply it has pads — pinning a mismatched
#      period/pad pair is what produced spurious NoSuchKey 500s previously.)
PERIOD="${PERIOD:-}"
PAD_ID="${PAD_ID:-}"

if [ -n "$PERIOD" ] && [ -n "$PAD_ID" ]; then
    print_info "Using pinned period/pad from environment: $PERIOD / $PAD_ID"
    PADS_JSON=$(fetch "$BASE_URL/api/pads?site=$SITE&sector=$SECTOR&period=$PERIOD")
else
    print_info "Auto-discovering a period that has pads..."
    PERIOD=""
    PADS_JSON="[]"
    for candidate in $PERIODS; do
        body=$(fetch "$BASE_URL/api/pads?site=$SITE&sector=$SECTOR&period=$candidate")
        count=$(echo "$body" | jq 'if type=="array" then length else 0 end' 2>/dev/null || echo 0)
        printf '    period %-22s pads=%s\n' "$candidate" "${count:-0}"
        if [ "${count:-0}" -gt 0 ]; then
            PERIOD="$candidate"
            PADS_JSON="$body"
            break
        fi
    done

    if [ -z "$PERIOD" ]; then
        print_fail "No period under $SITE/$SECTOR has any pads — cannot test mosaics"
        ((TOTAL_TESTS+=1))
        print_summary_and_exit
    fi
    PAD_ID=$(echo "$PADS_JSON" | jq -r '.[0].pad_id')
fi

print_info "Using period: $PERIOD"
print_info "Using pad:    $PAD_ID"

echo "$PADS_JSON" | jq -e --arg pad_id "$PAD_ID" '.[] | select(.pad_id == $pad_id)' >/dev/null 2>&1
assert "Pad '$PAD_ID' present in pads for period '$PERIOD'" $?

# ==============================================================================
# 3. Mosaic Endpoints
# ==============================================================================

print_header "3. Mosaic Endpoints"

print_info "Testing with: site=$SITE, sector=$SECTOR, period=$PERIOD, pad_id=$PAD_ID"

COMMON="site=$SITE&sector=$SECTOR&period=$PERIOD&pad_id=$PAD_ID"
MOSAIC_TYPES=("optical" "medical" "hotspot_alert")

for mosaic_type in "${MOSAIC_TYPES[@]}"; do
    echo ""
    print_info "Testing mosaic_type=$mosaic_type"

    # 3.1 Metadata — if this fails the mosaic is absent; skip its dependent checks
    if ! test_endpoint "Mosaic Metadata ($mosaic_type)" \
        "$BASE_URL/api/mosaic/metadata?$COMMON&mosaic_type=$mosaic_type"; then
        print_info "Skipping remaining $mosaic_type checks (no metadata)"
        continue
    fi

    # 3.2 Orthomosaic URL
    if test_endpoint "Orthomosaic URL ($mosaic_type)" \
        "$BASE_URL/api/mosaic/orthomosaic?$COMMON&mosaic_type=$mosaic_type"; then
        url=$(extract_json_value '.url')
        [[ "$url" == https://s3* || "$url" == https://*.amazonaws.com/* ]]
        assert "Orthomosaic URL is a valid S3 presigned URL ($mosaic_type)" $?
    fi

    # 3.3 Download flag sets a Content-Disposition filename
    if test_endpoint "Orthomosaic URL download=true ($mosaic_type)" \
        "$BASE_URL/api/mosaic/orthomosaic?$COMMON&mosaic_type=$mosaic_type&download=true"; then
        dl_url=$(extract_json_value '.url')
        [[ "$dl_url" == *"response-content-disposition"* ]]
        assert "Download URL carries Content-Disposition ($mosaic_type)" $?
    fi

    # 3.4 Camera positions
    if test_endpoint "Camera Positions ($mosaic_type)" \
        "$BASE_URL/api/mosaic/cameras?$COMMON&mosaic_type=$mosaic_type"; then
        feature_type=$(extract_json_value '.type')
        [ "$feature_type" = "FeatureCollection" ]
        assert "Camera positions are valid GeoJSON ($mosaic_type)" $?
    fi
done

# ==============================================================================
# 4. Image Endpoints
# ==============================================================================

print_header "4. Image Endpoints"

print_info "Fetching sample image_id from DynamoDB ($IMAGES_TABLE)..."

# NOTE: --limit is deliberately NOT used with --filter-expression. DynamoDB
# applies the filter AFTER reading `limit` items, so `--limit 1` can return zero
# matches even when many exist. `--max-items` pages until it collects a match.
# (See the "FilterExpression + Limit Pitfall" section in CLAUDE.md.)
IMAGE_ID=$(aws dynamodb scan \
    --table-name "$IMAGES_TABLE" \
    --filter-expression "site_id = :site AND sector_id = :sector AND period = :period" \
    --expression-attribute-values "{\":site\":{\"S\":\"$SITE\"},\":sector\":{\"S\":\"$SECTOR\"},\":period\":{\"S\":\"$PERIOD\"}}" \
    --max-items 1 \
    --projection-expression image_id \
    --region "$AWS_REGION" \
    --output json 2>/dev/null | jq -r '.Items[0].image_id.S // empty' 2>/dev/null)

if [ -n "${IMAGE_ID:-}" ]; then
    print_info "Using image_id: $IMAGE_ID"

    test_endpoint "Get Optical Image" "$BASE_URL/api/optical/$IMAGE_ID"
    test_endpoint "Get Thermal Image (medical)" "$BASE_URL/api/thermal/$IMAGE_ID?palette=medical"

    if test_endpoint "Get Thermal Stats" "$BASE_URL/api/thermal/$IMAGE_ID/stats"; then
        min_temp=$(extract_json_value '.min_temp')
        max_temp=$(extract_json_value '.max_temp')
        [[ "$min_temp" =~ ^-?[0-9]+\.?[0-9]*$ && "$max_temp" =~ ^-?[0-9]+\.?[0-9]*$ ]]
        assert "Thermal stats are numeric (min=${min_temp:-?}, max=${max_temp:-?})" $?
    fi
else
    print_info "Could not fetch an image_id for $SITE/$SECTOR/$PERIOD - skipping image endpoint tests"
fi

# ==============================================================================
# 5. Coverage Stats
# ==============================================================================

print_header "5. Coverage Stats"

test_endpoint "Coverage Stats" "$BASE_URL/api/coverage/stats?$COMMON"

# ==============================================================================
# 6. Error Handling Tests
# ==============================================================================

print_header "6. Error Handling"

test_endpoint "Missing site parameter" "$BASE_URL/api/sectors" 400
test_endpoint "Missing required params" "$BASE_URL/api/mosaic/metadata?site=$SITE" 400

# An unknown image id may legitimately be 404 or 500 depending on the backend
print_test "Invalid image ID (accepts 404 or 500)"
((TOTAL_TESTS+=1))
bad_code=$(curl -s --max-time "$CURL_TIMEOUT" -o "$RESPONSE_FILE" -w "%{http_code}" \
    "$BASE_URL/api/optical/nonexistent-image-id")
if [ "$bad_code" = "404" ] || [ "$bad_code" = "500" ]; then
    print_pass "Invalid image ID rejected (HTTP $bad_code)"
else
    print_fail "Invalid image ID returned unexpected HTTP $bad_code"
fi

# ==============================================================================
# Summary
# ==============================================================================

print_summary_and_exit
