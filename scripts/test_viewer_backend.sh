#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Thermal Viewer Backend - Automated Test Script
# ==============================================================================
# Purpose: Validate all viewer backend endpoints
# Usage: ./scripts/test_viewer_backend.sh
# ==============================================================================

BASE_URL="${BASE_URL:-https://dev-thermal.iabuilders.ai/viewer}"
VERBOSE="${VERBOSE:-false}"

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

print_pass() {
    echo -e "${GREEN}✓ PASS:${NC} $1"
    ((PASSED_TESTS+=1))
}

print_fail() {
    echo -e "${RED}✗ FAIL:${NC} $1"
    ((FAILED_TESTS+=1))
}

print_info() {
    echo -e "${BLUE}ℹ INFO:${NC} $1"
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

    # Make request and capture response
    http_code=$(curl -s -o /tmp/test_response.json -w "%{http_code}" "$url")

    if [ "$http_code" -eq "$expected_status" ]; then
        print_pass "$name (HTTP $http_code)"

        if [ "$VERBOSE" = "true" ] && [ -f /tmp/test_response.json ]; then
            echo "  Response:"
            cat /tmp/test_response.json | jq '.' 2>/dev/null || cat /tmp/test_response.json
        fi

        return 0
    else
        print_fail "$name (HTTP $http_code, expected $expected_status)"

        if [ -f /tmp/test_response.json ]; then
            echo "  Response:"
            cat /tmp/test_response.json
        fi

        return 1
    fi
}

extract_json_value() {
    local key="$1"
    # Disable pipefail temporarily to prevent script exit on jq errors
    set +e
    local value=$(jq -r "$key" /tmp/test_response.json 2>/dev/null)
    local exit_code=$?
    set -e

    if [ $exit_code -eq 0 ] && [ -n "$value" ] && [ "$value" != "null" ]; then
        echo "$value"
    else
        echo ""
    fi
}

# ==============================================================================
# Test Suite
# ==============================================================================

echo -e "${GREEN}Thermal Viewer Backend - Test Suite${NC}"
echo "Base URL: $BASE_URL"
echo ""

# ==============================================================================
# 1. Health Check
# ==============================================================================

print_header "1. Health Check"

test_endpoint "Health Endpoint" "$BASE_URL/health"

status=$(extract_json_value '.status')
if [ "$status" = "healthy" ]; then
    print_pass "Service status is healthy"
    ((PASSED_TESTS+=1))
else
    print_fail "Service status is not healthy (got: $status)"
    ((FAILED_TESTS+=1))
fi
((TOTAL_TESTS+=1))

# ==============================================================================
# 2. Data Discovery
# ==============================================================================

print_header "2. Data Discovery"

# 2.1 Get Sites
test_endpoint "Get Sites" "$BASE_URL/api/sites"

# Use known good site/sector/period/pad with complete mosaic data
SITE="leyte"
SECTOR="mahanagdong-b"

print_info "Using test site: $SITE"
print_info "Using test sector: $SECTOR"

# Verify the site exists in the API response
SITES=$(cat /tmp/test_response.json)
if echo "$SITES" | jq -e --arg site "$SITE" '.[] | select(. == $site)' > /dev/null 2>&1; then
    print_info "Confirmed site '$SITE' exists in API"
else
    print_fail "Site '$SITE' not found in API response"
    exit 1
fi

# 2.2 Get Sectors
test_endpoint "Get Sectors for $SITE" "$BASE_URL/api/sectors?site=$SITE"

# Verify the sector exists in the API response
SECTORS=$(cat /tmp/test_response.json)
if echo "$SECTORS" | jq -e --arg sector "$SECTOR" '.[] | select(. == $sector)' > /dev/null 2>&1; then
    print_info "Confirmed sector '$SECTOR' exists in API"
else
    print_fail "Sector '$SECTOR' not found in API response"
    exit 1
fi

# 2.3 Get Periods
test_endpoint "Get Periods for $SITE/$SECTOR" "$BASE_URL/api/periods?site=$SITE&sector=$SECTOR"

# Use specific period known to have complete mosaic data
PERIOD="20241230"

print_info "Using test period: $PERIOD"

# Verify the period exists in the API response
PERIODS=$(cat /tmp/test_response.json)
if echo "$PERIODS" | jq -e --arg period "$PERIOD" '.[] | select(. == $period)' > /dev/null 2>&1; then
    print_info "Confirmed period '$PERIOD' exists in API"
else
    print_fail "Period '$PERIOD' not found in API response"
    exit 1
fi

# 2.4 Get Pads
test_endpoint "Get Pads for $SITE/$SECTOR" "$BASE_URL/api/pads?site=$SITE&sector=$SECTOR"

# Use specific pad known to have complete mosaic data
PAD_ID="leyte_mahanagdong-b_PAD_mgdl"

print_info "Using test pad: $PAD_ID"

# Verify the pad exists in the API response
PADS=$(cat /tmp/test_response.json)
if echo "$PADS" | jq -e --arg pad_id "$PAD_ID" '.[] | select(.pad_id == $pad_id)' > /dev/null 2>&1; then
    print_info "Confirmed pad '$PAD_ID' exists in API"
else
    print_fail "Pad '$PAD_ID' not found in API response"
    exit 1
fi

# ==============================================================================
# 3. Mosaic Endpoints
# ==============================================================================

print_header "3. Mosaic Endpoints"

print_info "Testing with: site=$SITE, sector=$SECTOR, period=$PERIOD, pad_id=$PAD_ID"

MOSAIC_TYPES=("optical" "medical" "hotspot_alert")

for mosaic_type in "${MOSAIC_TYPES[@]}"; do
    echo ""
    print_info "Testing mosaic_type=$mosaic_type"

    # 3.1 Mosaic Metadata
    test_endpoint "Mosaic Metadata ($mosaic_type)" \
        "$BASE_URL/api/mosaic/metadata?site=$SITE&sector=$SECTOR&period=$PERIOD&pad_id=$PAD_ID&mosaic_type=$mosaic_type" \
        || continue  # Skip if metadata not found

    # 3.2 Orthomosaic URL
    test_endpoint "Orthomosaic URL ($mosaic_type)" \
        "$BASE_URL/api/mosaic/orthomosaic?site=$SITE&sector=$SECTOR&period=$PERIOD&pad_id=$PAD_ID&mosaic_type=$mosaic_type"

    # Verify URL is valid
    url=$(extract_json_value '.url')
    if [[ "$url" == https://s3* ]] || [[ "$url" == https://*.amazonaws.com/* ]]; then
        ((TOTAL_TESTS+=1))
        print_pass "Orthomosaic URL is valid S3 presigned URL"
        ((PASSED_TESTS+=1))
    else
        ((TOTAL_TESTS+=1))
        print_fail "Orthomosaic URL doesn't look like S3 URL: $url"
        ((FAILED_TESTS+=1))
    fi

    # 3.3 Camera Positions
    test_endpoint "Camera Positions ($mosaic_type)" \
        "$BASE_URL/api/mosaic/cameras?site=$SITE&sector=$SECTOR&period=$PERIOD&pad_id=$PAD_ID&mosaic_type=$mosaic_type"

    # Verify GeoJSON structure
    feature_type=$(extract_json_value '.type')
    if [ "$feature_type" = "FeatureCollection" ]; then
        ((TOTAL_TESTS+=1))
        print_pass "Camera positions returned valid GeoJSON"
        ((PASSED_TESTS+=1))
    else
        ((TOTAL_TESTS+=1))
        print_fail "Camera positions not valid GeoJSON (type=$feature_type)"
        ((FAILED_TESTS+=1))
    fi
done

# ==============================================================================
# 4. Image Endpoints
# ==============================================================================

print_header "4. Image Endpoints"

# Get an image_id from the images table
# We'll use AWS CLI to query an actual image
print_info "Fetching sample image_id from DynamoDB..."

IMAGE_ID=$(aws dynamodb scan \
    --table-name thermal-api-dev-images-7ecb7171 \
    --filter-expression "site_id = :site AND sector_id = :sector AND period = :period" \
    --expression-attribute-values "{\":site\":{\"S\":\"$SITE\"},\":sector\":{\"S\":\"$SECTOR\"},\":period\":{\"S\":\"$PERIOD\"}}" \
    --limit 1 \
    --projection-expression image_id \
    --region ap-southeast-1 \
    --output json 2>/dev/null | jq -r '.Items[0].image_id.S' || echo "")

if [ -n "$IMAGE_ID" ] && [ "$IMAGE_ID" != "null" ]; then
    print_info "Using image_id: $IMAGE_ID"

    # 4.1 Optical Image
    test_endpoint "Get Optical Image" "$BASE_URL/api/optical/$IMAGE_ID"

    # 4.2 Thermal Image (with palette)
    test_endpoint "Get Thermal Image (medical)" "$BASE_URL/api/thermal/$IMAGE_ID?palette=medical"

    # 4.3 Thermal Stats
    test_endpoint "Get Thermal Stats" "$BASE_URL/api/thermal/$IMAGE_ID/stats"

    # Verify stats have numeric values
    min_temp=$(extract_json_value '.min_temp')
    max_temp=$(extract_json_value '.max_temp')

    if [[ "$min_temp" =~ ^-?[0-9]+\.?[0-9]*$ ]] && [[ "$max_temp" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        ((TOTAL_TESTS+=1))
        print_pass "Thermal stats returned valid temperature values (min=$min_temp, max=$max_temp)"
        ((PASSED_TESTS+=1))
    else
        ((TOTAL_TESTS+=1))
        print_fail "Thermal stats temperature values invalid (min=$min_temp, max=$max_temp)"
        ((FAILED_TESTS+=1))
    fi
else
    print_info "Could not fetch image_id - skipping image endpoint tests"
fi

# ==============================================================================
# 5. Coverage Stats
# ==============================================================================

print_header "5. Coverage Stats"

test_endpoint "Coverage Stats" \
    "$BASE_URL/api/coverage/stats?site=$SITE&sector=$SECTOR&period=$PERIOD&pad_id=$PAD_ID"

# ==============================================================================
# 6. Error Handling Tests
# ==============================================================================

print_header "6. Error Handling"

# Test missing parameters
test_endpoint "Missing site parameter" "$BASE_URL/api/sectors" 400
test_endpoint "Missing required params" "$BASE_URL/api/mosaic/metadata?site=$SITE" 400
test_endpoint "Invalid image ID" "$BASE_URL/api/optical/nonexistent-image-id" || true  # May be 404 or 500

# ==============================================================================
# Summary
# ==============================================================================

print_header "Test Summary"

echo -e "Total Tests:  $TOTAL_TESTS"
echo -e "${GREEN}Passed:       $PASSED_TESTS${NC}"
echo -e "${RED}Failed:       $FAILED_TESTS${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "\n${GREEN}✓ All tests passed!${NC}\n"
    exit 0
else
    echo -e "\n${RED}✗ Some tests failed${NC}\n"
    exit 1
fi