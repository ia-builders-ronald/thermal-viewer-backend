# Thermal Viewer Backend Test Plan

## Overview
Comprehensive validation of all viewer backend endpoints to ensure proper data retrieval, S3 presigned URLs, and error handling.

## Test Environment
- **Base URL**: https://dev-thermal.iabuilders.ai/viewer
- **Backend Port**: 5001
- **AWS Region**: ap-southeast-1
- **DynamoDB Tables**: thermal-api-dev-{images,jobs,pads}-7ecb7171
- **S3 Bucket**: thermal-api-dev-storage-7ecb7171

---

## Test Categories

### 1. Health Check
**Endpoint**: `GET /health`

**Expected**:
- Status: 200 OK
- Response contains: `{"service":"thermal-viewer-backend","status":"healthy","version":"1.0.0"}`

**Pass Criteria**: Health endpoint returns healthy status

---

### 2. Data Discovery Endpoints

#### 2.1 Get Sites
**Endpoint**: `GET /api/sites`

**Expected**:
- Status: 200 OK
- Response: Array of site names (e.g., `["leyte"]`)
- Array should contain at least one site

**Pass Criteria**: Returns non-empty list of sites from pads table

---

#### 2.2 Get Sectors
**Endpoint**: `GET /api/sectors?site=leyte`

**Expected**:
- Status: 200 OK
- Response: Array of sector names (e.g., `["tongonan", "malitbog", "mahanagdong-b"]`)
- Array should contain at least one sector

**Error Cases**:
- Missing `site` parameter → 400 Bad Request with error message

**Pass Criteria**: Returns sectors for the specified site

---

#### 2.3 Get Periods
**Endpoint**: `GET /api/periods?site=leyte&sector=tongonan`

**Expected**:
- Status: 200 OK
- Response: Array of periods in descending order (most recent first)
- Format: YYYYMMDD or YYYYMMDD-SUFFIX (e.g., `["20250409-TGN-SS1", "20250228-TGN-SS2"]`)

**Error Cases**:
- Missing `site` or `sector` → 400 Bad Request

**Pass Criteria**: Returns periods sorted by recency

---

#### 2.4 Get Pads
**Endpoint**: `GET /api/pads?site=leyte&sector=tongonan`

**Expected**:
- Status: 200 OK
- Response: Array of pad objects with structure:
  ```json
  [
    {
      "pad_id": "leyte_tongonan_PAD_105",
      "pad_name": "105",
      "geo_location_area": [[lng, lat], [lng, lat], ...]
    }
  ]
  ```

**Error Cases**:
- Missing `site` or `sector` → 400 Bad Request

**Pass Criteria**: Returns pads with valid polygon coordinates

---

### 3. Mosaic Viewer Endpoints

#### 3.1 Get Mosaic Metadata
**Endpoint**: `GET /api/mosaic/metadata?site=leyte&sector=tongonan&period=20250409-TGN-SS1&pad_id=leyte_tongonan_PAD_105&mosaic_type=optical`

**Expected**:
- Status: 200 OK
- Response contains:
  - Job metadata (status, created_at, completed_at)
  - Image count statistics
  - Processing duration
  - Mosaic file paths

**Error Cases**:
- Missing required parameters → 400 Bad Request
- Mosaic job not found → 404 or error response

**Pass Criteria**: Returns metadata for completed mosaic job

---

#### 3.2 Get Orthomosaic URL
**Endpoint**: `GET /api/mosaic/orthomosaic?site=leyte&sector=tongonan&period=20250409-TGN-SS1&pad_id=leyte_tongonan_PAD_105&mosaic_type=optical`

**Expected**:
- Status: 200 OK
- Response: `{"url": "https://s3.ap-southeast-1.amazonaws.com/..."}`
- URL should be a valid S3 presigned URL
- URL should contain authentication query parameters

**Error Cases**:
- Missing parameters → 400 Bad Request
- Orthomosaic file doesn't exist → 404 or error

**Pass Criteria**: Returns valid presigned URL that can be downloaded

---

#### 3.3 Get Camera Positions
**Endpoint**: `GET /api/mosaic/cameras?site=leyte&sector=tongonan&period=20250409-TGN-SS1&pad_id=leyte_tongonan_PAD_105&mosaic_type=optical`

**Expected**:
- Status: 200 OK
- Response: GeoJSON FeatureCollection with Point features
- Each feature has:
  - `type`: "Feature"
  - `geometry.type`: "Point"
  - `geometry.coordinates`: [lng, lat]
  - `properties.image_id`, `properties.filename`

**Pass Criteria**: Returns valid GeoJSON with camera locations

---

### 4. Image Endpoints

#### 4.1 Get Optical Image
**Endpoint**: `GET /api/optical/{image_id}`

**Test Data**: Use actual image_id from DynamoDB

**Expected**:
- Status: 200 OK
- Response: `{"url": "https://s3..."}`
- URL points to optical image (W.JPG)

**Pass Criteria**: Returns valid presigned URL for optical image

---

#### 4.2 Get Thermal Image
**Endpoint**: `GET /api/thermal/{image_id}?palette=medical`

**Test Data**: Use actual image_id from DynamoDB

**Expected**:
- Status: 200 OK
- Response: `{"url": "https://s3..."}`
- URL points to colored thermal image (T_medical.JPG)

**Pass Criteria**: Returns valid presigned URL for colored thermal image

---

#### 4.3 Get Thermal Stats
**Endpoint**: `GET /api/thermal/{image_id}/stats`

**Expected**:
- Status: 200 OK
- Response contains:
  ```json
  {
    "min_temp": <number>,
    "max_temp": <number>,
    "mean_temp": <number>,
    "median_temp": <number>
  }
  ```

**Pass Criteria**: Returns temperature statistics as floats

---

### 5. Coverage Stats Endpoint

**Endpoint**: `GET /api/coverage/stats?site=leyte&sector=tongonan&period=20250409-TGN-SS1&pad_id=leyte_tongonan_PAD_105`

**Expected**:
- Status: 200 OK
- Response contains:
  - Total images count
  - Coverage percentage
  - Missing areas (if any)

**Pass Criteria**: Returns coverage statistics for the pad

---

## Test Execution Order

1. Health Check (baseline)
2. Data Discovery (sites → sectors → periods → pads)
3. Pick valid test data from discovery results
4. Mosaic endpoints (metadata → orthomosaic → cameras)
5. Image endpoints (optical → thermal → stats)
6. Coverage stats

---

## Success Criteria

- All health checks pass
- Data discovery returns non-empty results for each level
- Mosaic endpoints return valid URLs and metadata
- Image endpoints return valid presigned URLs
- All URLs are accessible (HTTP 200 when fetched)
- No 500 Internal Server Errors
- Appropriate error messages for invalid requests

---

## Known Limitations

- Q4/PAD_106 will NOT appear in results (mosaic prep failed due to EXIF issue)
- Only pads with completed mosaics will have orthomosaic URLs
- Presigned URLs expire after 1 hour (default)

---

## Automated Testing

See `scripts/test_viewer_backend.sh` for automated test execution.
