# Product Requirements Document (PRD)
# Thermal Viewer Backend API

**Version:** 1.0
**Date:** 2025-11-22
**Status:** Production
**Author:** Thermal Viewer Development Team

---

## Executive Summary

The Thermal Viewer Backend is a production-ready Flask REST API that provides secure, read-only access to thermal imagery datasets stored in AWS (S3 and DynamoDB). The API enables hierarchical navigation through geothermal site data, delivers orthomosaic imagery via presigned URLs, enriches camera position data with thermal metadata, and provides temperature statistics for analysis.

This document serves as the definitive technical specification and API reference for the backend system.

---

## 1. Project Overview

### 1.1 Purpose

Provide a scalable, secure REST API layer that:
- Exposes thermal imagery datasets through hierarchical navigation (Site → Sector → Period → Pad)
- Generates secure, time-limited access to S3-stored imagery via presigned URLs
- Enriches OpenDroneMap geospatial data with DynamoDB thermal metadata
- Delivers temperature statistics for thermal analysis
- Supports the thermal-viewer-frontend React application

### 1.2 System Context

```
┌─────────────────────────────────────────────────────────┐
│  Thermal Viewer Frontend (React)                        │
│  - User Interface                                       │
│  - Map Visualization                                    │
│  - Image Display                                        │
└────────────────┬────────────────────────────────────────┘
                 │ HTTPS (REST API)
                 ↓
┌─────────────────────────────────────────────────────────┐
│  nginx Reverse Proxy                                    │
│  /viewer/api/* → localhost:5001                         │
└────────────────┬────────────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────────────┐
│  Thermal Viewer Backend (Flask)                         │
│  - REST API Endpoints                                   │
│  - Business Logic (Service Layer)                       │
│  - AWS Integration (boto3)                              │
└────┬──────────────────────────────────┬─────────────────┘
     │                                   │
     ↓                                   ↓
┌──────────────────┐           ┌──────────────────────────┐
│  DynamoDB Tables │           │  S3 Bucket               │
│  - images        │           │  - Orthomosaics (GeoTIFF)│
│  - pads          │           │  - Camera Images (JPEG)  │
│  - jobs          │           │  - Colored Thermals      │
└──────────────────┘           └──────────────────────────┘
```

### 1.3 Key Capabilities

**Read-Only API:** No data mutations, only retrieval and URL generation
**Hierarchical Navigation:** Progressive discovery from site to specific pad
**Secure File Access:** Presigned S3 URLs with 1-hour expiration
**Data Enrichment:** Combines S3 files with DynamoDB metadata
**Production-Ready:** Dockerized, health-checked, logged, deployed to EC2

---

## 2. Technology Stack

### 2.1 Runtime & Framework

| Component | Version | Purpose |
|-----------|---------|---------|
| **Python** | 3.9 | Runtime environment |
| **Flask** | 3.0.0 | Web framework for REST API |
| **Flask-CORS** | 4.0.0 | Cross-Origin Resource Sharing |
| **Werkzeug** | (Flask bundled) | Production WSGI server |

### 2.2 AWS SDK & Tools

| Component | Version | Purpose |
|-----------|---------|---------|
| **boto3** | 1.34.0 | AWS SDK for Python (S3, DynamoDB) |
| **pyproj** | 3.6.0 | Coordinate system transformations |

### 2.3 AWS Services

**Amazon S3:**
- **Bucket:** `thermal-api-dev-storage-7ecb7171`
- **Region:** ap-southeast-1
- **Access Pattern:** Presigned URLs (read-only, 1-hour expiration)
- **Storage:**
  - Orthomosaic GeoTIFFs (optical, medical, hotspot_alert)
  - OpenDroneMap outputs (shots.geojson, odm_orthophoto.tif)
  - Camera images (optical JPEG, thermal JPEG)
  - Colored thermal images (medical palette, hotspot_alert palette)

**Amazon DynamoDB:**
- **Tables:**
  - `thermal-api-dev-images-7ecb7171` (image metadata, thermal stats)
  - `thermal-api-dev-pads-7ecb7171` (pad definitions, geospatial boundaries)
  - `thermal-api-dev-jobs-7ecb7171` (mosaic processing jobs - not currently used)
- **Region:** ap-southeast-1
- **Access Pattern:** Query via GSIs, GetItem for single records

**Amazon ECR:**
- **Repository:** `058264237306.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend`
- **Image Tag:** `latest`
- **Purpose:** Docker image storage for EC2 deployment

### 2.4 Infrastructure

**Deployment:**
- **Platform:** Amazon EC2 (t3.medium)
- **Container:** Docker (Docker Compose orchestration)
- **Reverse Proxy:** nginx (HTTPS termination, path rewriting)
- **Domain:** `https://dev-thermal.iabuilders.ai/viewer`

**Monitoring:**
- **Health Checks:** `/health` endpoint (30s interval)
- **Logging:** Docker json-file driver (10MB max, 3 file rotation)
- **Metrics:** CloudWatch (via Docker logs)

---

## 3. System Architecture

### 3.1 Component Architecture

```
┌───────────────────────────────────────────────────────────┐
│  app.py (Flask Application)                               │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  HTTP Layer (Route Handlers)                        │  │
│  │  - Parameter validation                             │  │
│  │  - Error handling                                   │  │
│  │  - JSON serialization                               │  │
│  └────────────┬────────────────────────────────────────┘  │
│               ↓                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Service Layer (Business Logic)                     │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │  │
│  │  │ MosaicService│ │CameraService │ │ImageService │ │  │
│  │  └──────────────┘ └──────────────┘ └─────────────┘ │  │
│  └────────────┬────────────────────────────────────────┘  │
│               ↓                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  AWS Integration Layer (boto3)                      │  │
│  │  - S3 Client (presigned URLs, file access)          │  │
│  │  - DynamoDB Resource (queries, scans, get_item)     │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

### 3.2 Service Layer Design

**MosaicService** (`services/mosaic_service.py`):
- **Responsibilities:**
  - Generate presigned URLs for orthomosaic GeoTIFFs
  - Retrieve mosaic metadata (image count, existence check)
  - Calculate coverage statistics (area, altitude, FOV)
  - Validate pad completeness (check required files exist in S3)
- **Dependencies:** S3 client, DynamoDB images table, DynamoDB jobs table

**CameraService** (`services/camera_service.py`):
- **Responsibilities:**
  - Fetch camera positions from S3 (shots.geojson)
  - Enrich GeoJSON with DynamoDB metadata (image IDs, thermal stats)
  - Extract and convert camera yaw from rotation data
- **Dependencies:** S3 client, DynamoDB images table

**ImageService** (`services/image_service.py`):
- **Responsibilities:**
  - Generate presigned URLs for optical camera images
  - Generate presigned URLs for colored thermal images
  - Retrieve thermal statistics (calibrated or original)
- **Dependencies:** S3 client, DynamoDB images table

### 3.3 Dependency Injection Pattern

**Initialization** (app.py lines 36-46):
```python
# Initialize AWS clients
s3_client = boto3.client('s3', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
images_table = dynamodb.Table(IMAGES_TABLE)
jobs_table = dynamodb.Table(JOBS_TABLE)
pads_table = dynamodb.Table(PADS_TABLE)

# Inject dependencies into services (constructor injection)
mosaic_service = MosaicService(s3_client, S3_BUCKET, images_table, jobs_table)
camera_service = CameraService(s3_client, S3_BUCKET, images_table)
image_service = ImageService(s3_client, S3_BUCKET, images_table)
```

**Benefits:**
- Testability (mock dependencies in unit tests)
- Loose coupling (services don't create their own clients)
- Clear dependency graph

---

## 4. API Reference

### 4.1 Base URL

**Production:** `https://dev-thermal.iabuilders.ai/viewer`
**Local Development:** `http://localhost:5001`

### 4.2 Common Patterns

**Response Format:** JSON
**Status Codes:**
- `200 OK` - Successful request
- `400 Bad Request` - Missing required parameters
- `500 Internal Server Error` - Server error, file not found, AWS error

**Error Response:**
```json
{
  "error": "Error message describing what went wrong"
}
```

**CORS:** Enabled for all origins (development mode)

---

### 4.3 Health & Root Endpoints

#### GET /health

**Description:** Health check endpoint for monitoring and load balancers

**Parameters:** None

**Response:**
```json
{
  "status": "healthy",
  "service": "thermal-viewer-backend",
  "version": "1.0.0"
}
```

**Status Codes:** `200 OK`

**Example:**
```bash
curl https://dev-thermal.iabuilders.ai/viewer/health
```

---

#### GET /

**Description:** API documentation root with endpoint listing

**Parameters:** None

**Response:**
```json
{
  "service": "Thermal Viewer Backend API",
  "version": "1.0.0",
  "endpoints": {
    "discovery": [
      "GET /api/sites",
      "GET /api/sectors?site={site}",
      "GET /api/periods?site={site}&sector={sector}",
      "GET /api/pads?site={site}&sector={sector}&period={period}"
    ],
    "mosaic": [
      "GET /api/mosaic/metadata?site={site}&sector={sector}&period={period}&pad_id={pad_id}&mosaic_type={type}",
      "GET /api/mosaic/orthomosaic?site={site}&sector={sector}&period={period}&pad_id={pad_id}&mosaic_type={type}",
      "GET /api/mosaic/cameras?site={site}&sector={sector}&period={period}&pad_id={pad_id}&mosaic_type={type}"
    ],
    "images": [
      "GET /api/optical/{image_id}",
      "GET /api/thermal/{image_id}?palette={palette}"
    ],
    "stats": [
      "GET /api/thermal/{image_id}/stats",
      "GET /api/coverage/stats?site={site}&sector={sector}&period={period}&pad_id={pad_id}"
    ]
  }
}
```

---

### 4.4 Discovery/Navigation Endpoints

#### GET /api/sites

**Description:** Get list of all available sites

**Parameters:** None

**Response:**
```json
["leyte"]
```

**Implementation:**
- Scans `pads` table for unique `site` values
- Handles DynamoDB reserved word `site` with ExpressionAttributeNames
- Returns alphabetically sorted

**Example:**
```bash
curl https://dev-thermal.iabuilders.ai/viewer/api/sites
```

**Implementation Details:**
- **DynamoDB Operation:** Scan
- **Table:** `pads`
- **Filter:** `attribute_exists(site)`
- **Pagination:** Handles LastEvaluatedKey for large tables

---

#### GET /api/sectors

**Description:** Get sectors for a specific site

**Parameters:**
| Name | Type   | Required | Description        |
|------|--------|----------|--------------------|
| site | string | Yes      | Site ID (e.g., "leyte") |

**Response:**
```json
["mahanagdong-a", "mahanagdong-b", "malitbog", "tongonan"]
```

**Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Missing `site` parameter
- `500 Internal Server Error` - DynamoDB error

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/sectors?site=leyte"
```

**Implementation Details:**
- **DynamoDB Operation:** Scan
- **Table:** `pads`
- **Filter:** `site = :site AND attribute_exists(sector)`
- **Returns:** Unique sectors, alphabetically sorted

---

#### GET /api/periods

**Description:** Get time periods for a site/sector combination

**Parameters:**
| Name   | Type   | Required | Description |
|--------|--------|----------|-------------|
| site   | string | Yes      | Site ID     |
| sector | string | Yes      | Sector ID   |

**Response:**
```json
["20250228", "20241230", "20241115"]
```

**Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Missing required parameters
- `500 Internal Server Error` - DynamoDB error

**Response Characteristics:**
- Format: YYYYMMDD or YYYYMMDD-SUFFIX (e.g., "20241231-PMSB")
- Sorted: Reverse chronological (most recent first)

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/periods?site=leyte&sector=tongonan"
```

**Implementation Details:**
- **DynamoDB Operation:** Scan
- **Table:** `images`
- **Filter:** `site_id = :site AND sector_id = :sector`
- **Extracts:** Unique `period` values
- **Sort:** Descending (newest first)

---

#### GET /api/pads

**Description:** Get pads for a site/sector, optionally filtered by completeness

**Parameters:**
| Name   | Type   | Required | Description                                    |
|--------|--------|----------|------------------------------------------------|
| site   | string | Yes      | Site ID                                        |
| sector | string | Yes      | Sector ID                                      |
| period | string | No       | If provided, only return pads with complete mosaics |

**Response:**
```json
[
  {
    "pad_id": "leyte_tongonan_PAD_105",
    "pad_name": "105",
    "geo_location_area": [
      [124.635123, 11.165456],
      [124.635789, 11.165456],
      [124.635789, 11.166123],
      [124.635123, 11.166123],
      [124.635123, 11.165456]
    ]
  },
  {
    "pad_id": "leyte_tongonan_PAD_tgn-ss1",
    "pad_name": "tgn-ss1",
    "geo_location_area": [...]
  }
]
```

**Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Missing required parameters
- `500 Internal Server Error` - DynamoDB error

**Completeness Check (when period is provided):**
A pad is considered "complete" if the following files exist in S3:
- `mosaics/{site}/{sector}/{period}/{pad_id}/optical/viewer/odm_orthophoto.tif`
- `mosaics/{site}/{sector}/{period}/{pad_id}/optical/viewer/shots.geojson`
- `mosaics/{site}/{sector}/{period}/{pad_id}/medical/viewer/odm_orthophoto.tif`
- `mosaics/{site}/{sector}/{period}/{pad_id}/medical/viewer/shots.geojson`

**Note:** `hotspot_alert` mosaic is NOT required for completeness (used by PipeMeasure workflow, not viewer)

**Example:**
```bash
# All pads for site/sector
curl "https://dev-thermal.iabuilders.ai/viewer/api/pads?site=leyte&sector=tongonan"

# Only complete pads for specific period
curl "https://dev-thermal.iabuilders.ai/viewer/api/pads?site=leyte&sector=tongonan&period=20241230"
```

**Implementation Details:**
- **DynamoDB Operation:** Query
- **Table:** `pads`
- **Index:** `SiteSectorDateIndex`
- **Key:** `site_sector = "{site}_{sector}"`
- **S3 Validation:** Uses `head_object` to check file existence (does not download)

---

### 4.5 Mosaic Endpoints

#### GET /api/mosaic/metadata

**Description:** Get mosaic job metadata and statistics

**Parameters:**
| Name        | Type   | Required | Default   | Description                      |
|-------------|--------|----------|-----------|----------------------------------|
| site        | string | Yes      | -         | Site ID                          |
| sector      | string | Yes      | -         | Sector ID                        |
| period      | string | Yes      | -         | Period (YYYYMMDD)                |
| pad_id      | string | Yes      | -         | Pad ID                           |
| mosaic_type | string | No       | "optical" | optical/medical/hotspot_alert    |

**Response:**
```json
{
  "exists": true,
  "image_count": 101,
  "site": "leyte",
  "sector": "tongonan",
  "period": "20241230",
  "pad_id": "leyte_tongonan_PAD_105",
  "mosaic_type": "optical"
}
```

**Fields:**
- `exists` (boolean) - Whether mosaic has been built
- `image_count` (integer) - Number of images in the pad
- `site`, `sector`, `period`, `pad_id`, `mosaic_type` - Echo input parameters

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/mosaic/metadata?site=leyte&sector=tongonan&period=20241230&pad_id=leyte_tongonan_PAD_105&mosaic_type=optical"
```

**Implementation Details:**
- **DynamoDB Operation:** Query
- **Table:** `images`
- **Index:** `SiteSectorPeriodIndex`
- **Key:** `site_id = :site AND sector_period = "{sector}#{period}"`
- **Filter:** `pad_id = :pad`
- **Checks:** `processing_status.mosaic_prep.mosaic_s3_keys[mosaic_type]` existence

---

#### GET /api/mosaic/orthomosaic

**Description:** Get presigned S3 URL for orthomosaic GeoTIFF

**Parameters:**
| Name        | Type   | Required | Default   | Description           |
|-------------|--------|----------|-----------|-----------------------|
| site        | string | Yes      | -         | Site ID               |
| sector      | string | Yes      | -         | Sector ID             |
| period      | string | Yes      | -         | Period                |
| pad_id      | string | Yes      | -         | Pad ID                |
| mosaic_type | string | No       | "optical" | optical/medical/hotspot_alert |

**Response:**
```json
{
  "url": "https://thermal-api-dev-storage-7ecb7171.s3.ap-southeast-1.amazonaws.com/mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/optical/viewer/odm_orthophoto.tif?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=...&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=..."
}
```

**URL Characteristics:**
- **Protocol:** HTTPS
- **Expiration:** 3600 seconds (1 hour)
- **Method:** GET (presigned)
- **File Type:** GeoTIFF (.tif)

**S3 Key Pattern:**
```
mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/viewer/odm_orthophoto.tif
```

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/mosaic/orthomosaic?site=leyte&sector=tongonan&period=20241230&pad_id=leyte_tongonan_PAD_105&mosaic_type=medical"
```

**Implementation Details:**
- **S3 Operation:** `generate_presigned_url` (does NOT validate file existence)
- **Expiration:** 3600 seconds
- **Region:** ap-southeast-1

**Important Notes:**
- URL is generated even if file does not exist
- Client will receive 403/404 when attempting to fetch non-existent file
- Use `/api/pads?period={period}` to get only pads with complete mosaics

---

#### GET /api/mosaic/cameras

**Description:** Get camera positions as GeoJSON FeatureCollection, enriched with thermal metadata

**Parameters:**
| Name        | Type   | Required | Default   | Description    |
|-------------|--------|----------|-----------|----------------|
| site        | string | Yes      | -         | Site ID        |
| sector      | string | Yes      | -         | Sector ID      |
| period      | string | Yes      | -         | Period         |
| pad_id      | string | Yes      | -         | Pad ID         |
| mosaic_type | string | No       | "optical" | Mosaic type    |

**Response:**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [124.635123, 11.165456, 445.5]
      },
      "properties": {
        "filename": "DJI_0380_W.JPG",
        "rotation": [2.222, 0.123, -0.045],
        "image_id": "leyte_tongonan_20241230_0379",
        "thermal_filename": "DJI_0381_T.JPG",
        "altitude": 445.5,
        "temp_max": 131.6,
        "temp_min": 22.7,
        "yaw": 127.3
      }
    }
  ]
}
```

**GeoJSON Structure:**
- **Geometry:** Point with [longitude, latitude, altitude]
- **Properties (from ODM):**
  - `filename` - Optical image filename
  - `rotation` - [yaw, pitch, roll] in radians (from OpenDroneMap)
- **Properties (enriched from DynamoDB):**
  - `image_id` - Unique identifier for API calls
  - `thermal_filename` - Thermal image filename
  - `altitude` - Camera altitude in meters
  - `temp_max` - Max temperature in thermal image (°C)
  - `temp_min` - Min temperature in thermal image (°C)
  - `yaw` - Camera heading in degrees (0-360, 0=North)

**Yaw Calculation:**
```python
# ODM provides rotation[0] (yaw) in radians
yaw_radians = feature['properties']['rotation'][0]
yaw_degrees = yaw_radians * (180 / math.pi)
yaw_normalized = yaw_degrees % 360  # Normalize to 0-360
```

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/mosaic/cameras?site=leyte&sector=tongonan&period=20241230&pad_id=leyte_tongonan_PAD_105&mosaic_type=optical"
```

**Implementation Details:**
- **S3 Fetch:** Downloads `shots.geojson` from S3
- **S3 Key:** `mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/viewer/shots.geojson`
- **DynamoDB Query:** Fetches metadata for all images in pad
- **Enrichment:** Maps ODM filenames to DynamoDB records, adds thermal data

---

### 4.6 Image Endpoints

#### GET /api/optical/{image_id}

**Description:** Get presigned S3 URL for optical camera image

**Parameters:**
| Name     | Type   | Location | Required | Description          |
|----------|--------|----------|----------|----------------------|
| image_id | string | Path     | Yes      | Image ID from DynamoDB |

**Path Pattern:** `/api/optical/{image_id}`

**Response:**
```json
{
  "url": "https://thermal-api-dev-storage-7ecb7171.s3.ap-southeast-1.amazonaws.com/images/leyte/tongonan/20241230/DJI_0380_W.JPG?X-Amz-Algorithm=AWS4-HMAC-SHA256&..."
}
```

**URL Characteristics:**
- **Expiration:** 3600 seconds (1 hour)
- **File Type:** JPEG (.JPG)
- **Format:** RGB optical image

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/optical/leyte_tongonan_20241230_0379"
```

**Implementation Details:**
- **DynamoDB Operation:** GetItem
- **Table:** `images`
- **Key:** `image_id`
- **Retrieves:** `optical_s3_key` attribute
- **S3 Operation:** Generate presigned URL

---

#### GET /api/thermal/{image_id}

**Description:** Get presigned S3 URL for colored thermal image

**Parameters:**
| Name     | Type   | Location | Required | Default    | Description                |
|----------|--------|----------|----------|------------|----------------------------|
| image_id | string | Path     | Yes      | -          | Image ID from DynamoDB     |
| palette  | string | Query    | No       | "medical"  | medical/hotspot_alert      |

**Path Pattern:** `/api/thermal/{image_id}?palette={palette}`

**Response:**
```json
{
  "url": "https://thermal-api-dev-storage-7ecb7171.s3.ap-southeast-1.amazonaws.com/colored/leyte/tongonan/20241230/DJI_0381_T_medical.JPG?X-Amz-Algorithm=AWS4-HMAC-SHA256&..."
}
```

**URL Characteristics:**
- **Expiration:** 3600 seconds (1 hour)
- **File Type:** JPEG (.JPG)
- **Format:** Colored thermal image (DJI palette pre-applied)

**Palette Options:**
- **`medical`** - DJI medical colormap (default) - optimized for detail, wide temperature range
- **`hotspot_alert`** - Grayscale colormap - used for PipeMeasure workflow

**Example:**
```bash
# Medical palette (default)
curl "https://dev-thermal.iabuilders.ai/viewer/api/thermal/leyte_tongonan_20241230_0379"

# Hotspot alert palette
curl "https://dev-thermal.iabuilders.ai/viewer/api/thermal/leyte_tongonan_20241230_0379?palette=hotspot_alert"
```

**Implementation Details:**
- **DynamoDB Operation:** GetItem
- **Table:** `images`
- **Key:** `image_id`
- **Retrieves:** `colored_images[palette]` attribute
- **Error:** Returns 500 if palette not found in colored_images

---

#### GET /api/thermal/{image_id}/stats

**Description:** Get temperature statistics for thermal image

**Parameters:**
| Name     | Type   | Location | Required | Description |
|----------|--------|----------|----------|-------------|
| image_id | string | Path     | Yes      | Image ID    |

**Path Pattern:** `/api/thermal/{image_id}/stats`

**Response (Calibrated):**
```json
{
  "min_temp": 22.7,
  "max_temp": 145.3,
  "avg_temp": 28.54,
  "is_calibrated": true,
  "palette": "medical",
  "calibration_params": {
    "emissivity": 0.92,
    "distance": 25.0,
    "reflection": 25.0,
    "ambient_temp": 25.0,
    "humidity": 50.0
  }
}
```

**Response (Uncalibrated):**
```json
{
  "min_temp": 22.7,
  "max_temp": 131.6,
  "avg_temp": 27.89,
  "is_calibrated": false,
  "palette": "medical",
  "original_params": {
    "emissivity": 1.0,
    "distance": 5.0,
    "reflection": 25.0,
    "ambient_temp": 20.0,
    "humidity": 70.0
  }
}
```

**Fields:**
- `min_temp` (float) - Minimum temperature (°C)
- `max_temp` (float) - Maximum temperature (°C)
- `avg_temp` (float) - Average temperature (°C)
- `is_calibrated` (boolean) - Whether calibration has been applied
- `palette` (string) - Colormap used
- `calibration_params` or `original_params` - Environmental parameters

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/thermal/leyte_tongonan_20241230_0379/stats"
```

**Implementation Details:**
- **DynamoDB Operation:** GetItem
- **Table:** `images`
- **Logic:**
  - If `calibration.status == "calibrated"`: return `calibration.temperature_delta` values
  - Else: return `thermal_metadata` original values
- **Type Conversion:** All Decimal types converted to float for JSON serialization

---

### 4.7 Stats Endpoints

#### GET /api/coverage/stats

**Description:** Get coverage statistics for a mosaic pad

**Parameters:**
| Name   | Type   | Required | Description |
|--------|--------|----------|-------------|
| site   | string | Yes      | Site ID     |
| sector | string | Yes      | Sector ID   |
| period | string | Yes      | Period      |
| pad_id | string | Yes      | Pad ID      |

**Response:**
```json
{
  "total_images": 101,
  "coverage_area_m2": 32891.45,
  "avg_altitude_m": 445.4,
  "camera_fov_deg": 68.9
}
```

**Fields:**
- `total_images` (integer) - Number of images in the pad
- `coverage_area_m2` (float) - Estimated coverage area in square meters
- `avg_altitude_m` (float) - Average camera altitude in meters
- `camera_fov_deg` (float) - Camera field of view in degrees (DJI M2EA: 68.9°)

**Coverage Area Calculation:**
```python
# Assumes DJI M2EA thermal camera
camera_fov = 68.9  # degrees
thermal_aspect = 512 / 640  # height/width

# Calculate ground coverage at average altitude
ground_width = 2 * avg_altitude * tan(fov_rad / 2)
ground_height = ground_width * thermal_aspect
area_per_image = ground_width * ground_height

# Account for 60% overlap (40% unique coverage)
total_area = area_per_image * image_count * 0.4
```

**Example:**
```bash
curl "https://dev-thermal.iabuilders.ai/viewer/api/coverage/stats?site=leyte&sector=tongonan&period=20241230&pad_id=leyte_tongonan_PAD_105"
```

**Implementation Details:**
- **DynamoDB Operation:** Query
- **Table:** `images`
- **Index:** `SiteSectorPeriodIndex`
- **Extracts:** Altitude from `optical_metadata.gps_location.altitude`
- **Calculation:** Geometric estimation (see formula above)

---

## 5. Data Models & Schemas

### 5.1 DynamoDB Table: Images

**Table Name:** `thermal-api-dev-images-7ecb7171`

**Primary Key:**
- **Partition Key:** `image_id` (String) - Format: `{site}_{sector}_{period}_{index}`
  - Example: `leyte_tongonan_20241230_0379`

**Global Secondary Indexes:**

**SiteSectorPeriodIndex:**
- **Partition Key:** `site_id` (String)
- **Sort Key:** `sector_period` (String) - Format: `{sector}#{period}`
- **Projection:** All attributes
- **Use Cases:** Query images for specific site/sector/period combination

**Attributes Schema:**
```python
{
  # Primary identifiers
  "image_id": "leyte_tongonan_20241230_0379",
  "site_id": "leyte",
  "sector_id": "tongonan",
  "period": "20241230",
  "pad_id": "leyte_tongonan_PAD_105",
  "sector_period": "tongonan#20241230",  # GSI sort key

  # File references
  "optical_filename": "DJI_0380_W.JPG",
  "thermal_filename": "DJI_0381_T.JPG",
  "optical_s3_key": "images/leyte/tongonan/20241230/DJI_0380_W.JPG",
  "thermal_s3_key": "images/leyte/tongonan/20241230/DJI_0381_T.JPG",

  # Colored thermal images
  "colored_images": {
    "medical": "colored/leyte/tongonan/20241230/DJI_0381_T_medical.JPG",
    "hotspot_alert": "colored/leyte/tongonan/20241230/DJI_0381_T_hotspot_alert.JPG"
  },

  # Optical metadata
  "optical_metadata": {
    "gps_location": {
      "latitude": Decimal("11.165456"),
      "longitude": Decimal("124.635123"),
      "altitude": Decimal("445.5")
    }
  },

  # Original thermal metadata (from DJI EXIF)
  "thermal_metadata": {
    "temperature_min": Decimal("22.7"),
    "temperature_max": Decimal("131.6"),
    "temperature_avg": Decimal("27.89"),
    "emissivity": Decimal("1.0"),
    "object_distance": Decimal("5.0"),
    "reflected_temperature": Decimal("25.0"),
    "ambient_temperature": Decimal("20.0"),
    "relative_humidity": Decimal("70.0")
  },

  # Calibration (if applied)
  "calibration": {
    "status": "calibrated",  # or "not_calibrated"
    "params": {
      "emissivity": Decimal("0.92"),
      "distance": Decimal("25.0"),
      "reflection": Decimal("25.0"),
      "ambient_temp": Decimal("25.0"),
      "humidity": Decimal("50.0")
    },
    "temperature_delta": {
      "max_calibrated": Decimal("145.3"),
      "avg_calibrated": Decimal("28.54")
    }
  },

  # Processing status (from thermal-api workflow)
  "processing_status": {
    "mosaic_prep": {
      "included_in": ["optical", "medical", "hotspot_alert"],
      "mosaic_s3_keys": {
        "optical": "mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/optical/viewer",
        "medical": "mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/medical/viewer",
        "hotspot_alert": "mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/hotspot_alert/viewer"
      }
    }
  }
}
```

**Data Types:**
- Numbers stored as `Decimal` (DynamoDB requirement)
- Backend converts Decimal → float for JSON responses
- Strings use UTF-8 encoding

---

### 5.2 DynamoDB Table: Pads

**Table Name:** `thermal-api-dev-pads-7ecb7171`

**Primary Key:**
- **Partition Key:** `pad_id` (String) - Format: `{site}_{sector}_PAD_{pad_name}`
  - Example: `leyte_tongonan_PAD_105`

**Global Secondary Indexes:**

**SiteSectorDateIndex:**
- **Partition Key:** `site_sector` (String) - Format: `{site}_{sector}`
- **Sort Key:** `effective_date` (String) - Format: YYYYMMDD
- **Projection:** All attributes
- **Use Cases:** Query pads for specific site/sector

**Attributes Schema:**
```python
{
  # Primary identifiers
  "pad_id": "leyte_tongonan_PAD_105",
  "site": "leyte",            # Note: some items may use "site_id"
  "sector": "tongonan",       # Note: some items may use "sector_id"
  "site_sector": "leyte_tongonan",  # GSI partition key
  "pad_name": "105",
  "effective_date": "20200101",  # GSI sort key

  # Geospatial boundary (polygon coordinates)
  "geo_location_area": [
    [Decimal("124.635123"), Decimal("11.165456")],  # [lon, lat]
    [Decimal("124.635789"), Decimal("11.165456")],
    [Decimal("124.635789"), Decimal("11.166123")],
    [Decimal("124.635123"), Decimal("11.166123")],
    [Decimal("124.635123"), Decimal("11.165456")]   # Closed polygon
  ]
}
```

**Notes:**
- Backend filters out items without `site` or `sector` attributes (handles inconsistent data)
- Polygon coordinates: [longitude, latitude] pairs (GeoJSON standard)
- Polygon must be closed (first point == last point)

---

### 5.3 S3 Object Structure

**Bucket:** `thermal-api-dev-storage-7ecb7171`
**Region:** ap-southeast-1

#### Mosaic Files (Viewer)
```
mosaics/
└── {site}/
    └── {sector}/
        └── {period}/
            └── {pad_id}/
                ├── optical/
                │   └── viewer/
                │       ├── odm_orthophoto.tif    # Required
                │       ├── shots.geojson         # Required
                │       └── (other ODM outputs)
                ├── medical/
                │   └── viewer/
                │       ├── odm_orthophoto.tif    # Required
                │       ├── shots.geojson         # Required
                │       └── (other ODM outputs)
                └── hotspot_alert/
                    └── viewer/
                        ├── odm_orthophoto.tif    # Optional (not required for viewer)
                        ├── shots.geojson
                        └── (other ODM outputs)
```

**Example Paths:**
```
mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/optical/viewer/odm_orthophoto.tif
mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/optical/viewer/shots.geojson
mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/medical/viewer/odm_orthophoto.tif
```

#### Camera Images
```
images/
└── {site}/
    └── {sector}/
        └── {period}/
            ├── DJI_0380_W.JPG  # Optical (RGB)
            ├── DJI_0381_T.JPG  # Thermal (radiometric)
            └── ...

colored/
└── {site}/
    └── {sector}/
        └── {period}/
            ├── DJI_0381_T_medical.JPG        # Medical palette
            ├── DJI_0381_T_hotspot_alert.JPG  # Hotspot alert palette
            └── ...
```

**File Formats:**
- **odm_orthophoto.tif:** GeoTIFF with embedded georeferencing
- **shots.geojson:** GeoJSON FeatureCollection with camera positions
- **Optical images:** JPEG with EXIF metadata
- **Thermal images:** Radiometric JPEG (DJI R-JPEG)
- **Colored thermals:** Standard JPEG with pre-applied color palette

---

### 5.4 GeoJSON Format (shots.geojson)

**Source:** OpenDroneMap mosaic build process

**Structure:**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [124.635123, 11.165456, 445.5]
      },
      "properties": {
        "filename": "DJI_0380_W.JPG",
        "rotation": [2.222, 0.123, -0.045]
      }
    }
  ]
}
```

**Enriched by Backend (CameraService):**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [124.635123, 11.165456, 445.5]
      },
      "properties": {
        "filename": "DJI_0380_W.JPG",
        "rotation": [2.222, 0.123, -0.045],

        "image_id": "leyte_tongonan_20241230_0379",
        "thermal_filename": "DJI_0381_T.JPG",
        "altitude": 445.5,
        "temp_max": 131.6,
        "temp_min": 22.7,
        "yaw": 127.3
      }
    }
  ]
}
```

**Coordinate Format:** [longitude, latitude, altitude] (GeoJSON standard)
**Rotation Format:** [yaw, pitch, roll] in radians (OpenDroneMap convention)

---

## 6. Configuration & Environment

### 6.1 Environment Variables

**Configuration File:** `app.py` (lines 29-34)

| Variable      | Default Value                     | Description                  |
|---------------|-----------------------------------|------------------------------|
| `AWS_REGION`  | ap-southeast-1                    | AWS region for all services  |
| `S3_BUCKET`   | thermal-api-dev-storage-7ecb7171  | S3 bucket for imagery        |
| `IMAGES_TABLE`| thermal-api-dev-images-7ecb7171   | DynamoDB images table        |
| `JOBS_TABLE`  | thermal-api-dev-jobs-7ecb7171     | DynamoDB jobs table          |
| `PADS_TABLE`  | thermal-api-dev-pads-7ecb7171     | DynamoDB pads table          |
| `PORT`        | 5001                              | Flask server port            |

**Docker Compose Override:**
```yaml
version: '3.8'
services:
  backend:
    environment:
      - AWS_REGION=ap-southeast-1
      - S3_BUCKET=thermal-api-dev-storage-7ecb7171
      - IMAGES_TABLE=thermal-api-dev-images-7ecb7171
      - JOBS_TABLE=thermal-api-dev-jobs-7ecb7171
      - PADS_TABLE=thermal-api-dev-pads-7ecb7171
      - PORT=5001
```

**Local Development:**
```bash
export AWS_REGION=ap-southeast-1
export S3_BUCKET=thermal-api-dev-storage-7ecb7171
export IMAGES_TABLE=thermal-api-dev-images-7ecb7171
export JOBS_TABLE=thermal-api-dev-jobs-7ecb7171
export PADS_TABLE=thermal-api-dev-pads-7ecb7171
python app.py
```

---

### 6.2 AWS Credentials

**Required Permissions:**

**S3:**
- `s3:GetObject` - Read files from bucket
- `s3:HeadObject` - Check file existence
- `s3:ListBucket` - (Optional) List bucket contents

**DynamoDB:**
- `dynamodb:GetItem` - Get single item by key
- `dynamodb:Query` - Query using indexes
- `dynamodb:Scan` - Scan entire table

**No Write Permissions Required** - Backend is read-only

**Credential Sources** (boto3 searches in this order):
1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. AWS credentials file (`~/.aws/credentials`)
3. IAM instance profile (EC2 deployment)
4. ECS task role (if deployed on ECS)

**EC2 Deployment:** Uses IAM instance profile (recommended)

---

### 6.3 Deployment Configuration

#### Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install GDAL (required by pyproj for coordinate transformations)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgdal-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Flask port
EXPOSE 5001

# Run Flask app
CMD ["python", "app.py"]
```

**Multi-stage Build:** Single-stage (optimization opportunity for future)
**Base Image:** python:3.9-slim (Debian-based)
**Dependencies:** GDAL system library for geospatial operations

---

#### docker-compose.yml

```yaml
version: '3.8'

services:
  backend:
    build: .
    container_name: thermal-viewer-backend
    ports:
      - "5001:5001"
    environment:
      - AWS_REGION=ap-southeast-1
      - S3_BUCKET=thermal-api-dev-storage-7ecb7171
      - IMAGES_TABLE=thermal-api-dev-images-7ecb7171
      - JOBS_TABLE=thermal-api-dev-jobs-7ecb7171
      - PADS_TABLE=thermal-api-dev-pads-7ecb7171
    volumes:
      - ~/.aws:/root/.aws:ro  # Mount AWS credentials
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**Health Check:** Curl `/health` endpoint every 30 seconds
**Restart Policy:** `unless-stopped` (auto-restart on failure)
**Log Rotation:** Max 10MB per file, keep 3 files

---

#### nginx Configuration

**File:** `/etc/nginx/sites-available/thermal-api-dev.conf`

```nginx
upstream thermal_viewer {
    server localhost:5001;
}

server {
    listen 443 ssl;
    server_name dev-thermal.iabuilders.ai;

    # SSL configuration (managed by Certbot)
    ssl_certificate /etc/letsencrypt/live/dev-thermal.iabuilders.ai/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dev-thermal.iabuilders.ai/privkey.pem;

    # Viewer backend routes
    location /viewer/api/ {
        rewrite ^/viewer/api/(.*) /api/$1 break;
        proxy_pass http://thermal_viewer;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /viewer/health {
        proxy_pass http://thermal_viewer/health;
        access_log off;  # Don't log health checks
    }

    # Frontend static files
    location /viewer/ {
        root /var/www/thermal-viewer-frontend;
        try_files $uri $uri/ /viewer/index.html;
    }
}
```

**Path Rewriting:** `/viewer/api/*` → `/api/*` (strips `/viewer` prefix)
**Health Check:** Proxies to `/health` without logging
**Frontend Serving:** Serves static files from `/var/www/thermal-viewer-frontend`

---

## 7. Error Handling & Logging

### 7.1 Error Handling Strategy

**Pattern:** Try-catch with informative error messages

**Example:**
```python
@app.route('/api/sites', methods=['GET'])
def get_sites():
    try:
        # Business logic
        sites = get_unique_sites()
        return jsonify(sites), 200
    except Exception as e:
        logger.error(f"Error fetching sites: {e}")
        return jsonify({'error': str(e)}), 500
```

**Status Codes:**
- **200 OK:** Successful operation
- **400 Bad Request:** Missing required parameters
- **500 Internal Server Error:** AWS errors, file not found, unexpected exceptions

**Error Response Format:**
```json
{
  "error": "Descriptive error message"
}
```

---

### 7.2 Logging Configuration

**Setup** (app.py lines 18-23):
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
```

**Log Levels:**
- **INFO:** Successful operations (orthomosaic generated, cameras fetched)
- **WARNING:** Filtered items (incomplete pads, missing attributes)
- **ERROR:** Exceptions and failures
- **DEBUG:** Detailed debugging (disabled in production)

**Example Logs:**
```
2025-11-22 10:30:45 - __main__ - INFO - Generated orthomosaic URL for mosaics/leyte/tongonan/20241230/leyte_tongonan_PAD_105/optical/viewer/odm_orthophoto.tif
2025-11-22 10:30:46 - __main__ - WARNING - leyte_tongonan_PAD_ssa: Missing hotspot_alert in mosaic_s3_keys
2025-11-22 10:30:47 - __main__ - ERROR - Error fetching camera positions: 'NoneType' object has no attribute 'read'
```

---

### 7.3 Special Error Cases

#### DynamoDB Reserved Words

**Problem:** `site` and `sector` are DynamoDB reserved keywords

**Solution:** Use `ExpressionAttributeNames`
```python
scan_kwargs = {
    'FilterExpression': '#site = :site AND attribute_exists(#sector)',
    'ExpressionAttributeNames': {
        '#site': 'site',
        '#sector': 'sector'
    },
    'ExpressionAttributeValues': {
        ':site': site
    }
}
```

---

#### Decimal to Float Conversion

**Problem:** DynamoDB returns `Decimal` type, not JSON-serializable

**Solution:** Recursive conversion helper (app.py lines 50-57)
```python
def decimal_to_float(obj):
    """Recursively convert Decimal to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(item) for item in obj]
    return obj
```

---

#### S3 File Not Found

**Scenario:** Presigned URL generated for non-existent file

**Current Behavior:**
- API returns 200 with presigned URL
- Client receives 403/404 when fetching URL

**Mitigation:**
- Use `/api/pads?period={period}` to get only complete pads
- `check_pad_completeness()` validates files before listing pads

---

## 8. Non-Functional Requirements

### 8.1 Performance

**Target Metrics:**
- **API Response Time:** <500ms (90th percentile)
- **Presigned URL Generation:** <100ms
- **DynamoDB Query:** <200ms
- **S3 File Fetch (shots.geojson):** <1s (depends on file size)

**Current Performance:**
- `/api/sites`: ~150ms
- `/api/sectors`: ~200ms
- `/api/pads`: ~300ms (without completeness check), ~2s (with check)
- `/api/mosaic/orthomosaic`: ~80ms (URL generation only)
- `/api/mosaic/cameras`: ~1.5s (includes S3 fetch + DynamoDB query)

**Optimization Opportunities:**
- Cache discovery endpoints (sites, sectors, periods)
- Use DynamoDB PartiQL for complex queries
- Implement CloudFront CDN for GeoTIFF files
- Use S3 Select for filtering large GeoJSON files

---

### 8.2 Scalability

**Current Deployment:**
- Single EC2 instance (t3.medium: 2 vCPU, 4GB RAM)
- Single Flask process (Werkzeug development server)
- No load balancer

**Scaling Strategy:**

**Vertical Scaling:**
- Upgrade to larger EC2 instance (t3.large, t3.xlarge)
- Increase worker processes (gunicorn with multiple workers)

**Horizontal Scaling:**
- Deploy multiple EC2 instances behind Application Load Balancer
- Use Auto Scaling Group for automatic scaling
- Session-less design allows stateless scaling

**Serverless Option (Future):**
- Migrate to AWS Lambda + API Gateway
- Pay-per-request pricing
- Automatic scaling to thousands of concurrent requests

---

### 8.3 Availability

**Target:** 99.5% uptime (43.8 hours downtime/year)

**Current SLA:**
- Single instance (no redundancy)
- EC2 instance availability: ~99.99% (AWS SLA)
- DynamoDB availability: 99.99% (AWS SLA)
- S3 availability: 99.99% (AWS SLA)

**Failure Modes:**
- EC2 instance failure → Manual restart or Auto Scaling Group
- nginx crash → systemd auto-restart
- Docker container crash → restart policy (unless-stopped)

**Monitoring:**
- Health check endpoint (`/health`) every 30 seconds
- CloudWatch logs for error tracking
- nginx access logs for request monitoring

---

### 8.4 Security

**Authentication:** None (public API for development)

**Authorization:** None (read-only data)

**Data Security:**
- **HTTPS Only:** nginx enforces SSL/TLS
- **Presigned URLs:** Time-limited (1 hour), no permanent public access
- **Read-Only:** Backend cannot modify DynamoDB or S3 data
- **CORS:** Enabled for all origins (development mode)

**Future Security Enhancements:**
- API key authentication
- JWT-based user authentication (Cognito)
- Rate limiting (API Gateway)
- CORS whitelist (production domains only)
- WAF (Web Application Firewall)

---

### 8.5 Observability

**Logging:**
- Application logs: Docker json-file driver
- nginx access logs: `/var/log/nginx/access.log`
- nginx error logs: `/var/log/nginx/error.log`

**Metrics:** (Future)
- CloudWatch custom metrics (request count, latency, errors)
- API Gateway metrics (if migrated to serverless)

**Tracing:** (Future)
- AWS X-Ray for distributed tracing
- Request correlation IDs

**Alerting:** (Future)
- CloudWatch Alarms for error rate, latency
- SNS notifications to operations team

---

## 9. Testing

### 9.1 Automated Test Script

**File:** `scripts/test_viewer_backend.sh`

**Coverage:**
- Health check endpoint
- All discovery endpoints (sites, sectors, periods, pads)
- All mosaic endpoints (metadata, orthomosaic, cameras)
- All image endpoints (optical, thermal, stats)
- All stats endpoints (coverage)

**Output:**
- Colored pass/fail indicators
- Response validation (structure, data types)
- HTTP status code checks

**Example:**
```bash
./scripts/test_viewer_backend.sh https://dev-thermal.iabuilders.ai/viewer
```

---

### 9.2 Manual Test Plan

**File:** `TEST_PLAN.md`

**Test Cases:**
1. Discovery flow (sites → sectors → periods → pads)
2. Mosaic loading (optical, medical)
3. Camera position enrichment
4. Image URL generation (optical, thermal)
5. Temperature statistics (calibrated, uncalibrated)
6. Coverage statistics calculation
7. Error handling (missing parameters, invalid IDs)
8. Completeness check (pads with/without mosaics)

---

## 10. Deployment

### 10.1 Build & Push to ECR

**Script:** `scripts/build_and_push_backend.sh`

**Steps:**
1. Auto-detect AWS account ID
2. Login to ECR
3. Build Docker image for linux/amd64 (EC2-compatible)
4. Tag image with `latest`
5. Push to ECR repository

**Usage:**
```bash
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-backend
./scripts/build_and_push_backend.sh
```

---

### 10.2 EC2 Deployment

**Instance Type:** t3.medium (2 vCPU, 4GB RAM)
**OS:** Amazon Linux 2 or Ubuntu 20.04 LTS
**Docker:** Docker CE + Docker Compose

**Deployment Steps:**
1. Pull latest image from ECR
2. Stop existing container
3. Start new container with docker-compose
4. Verify health check passes
5. Check nginx reverse proxy configuration

**Commands:**
```bash
# Login to ECR
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com

# Pull latest
docker pull 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend:latest

# Restart service
cd /path/to/thermal-viewer-backend
docker-compose down
docker-compose up -d

# Check logs
docker-compose logs -f backend
```

---

### 10.3 Production Checklist

**Before Deployment:**
- [ ] Run automated tests (`test_viewer_backend.sh`)
- [ ] Review code changes (git log)
- [ ] Update version in `app.py`
- [ ] Build and push Docker image to ECR
- [ ] Test in staging environment

**During Deployment:**
- [ ] SSH to EC2 instance
- [ ] Pull latest image
- [ ] Stop old container gracefully
- [ ] Start new container
- [ ] Verify health check endpoint
- [ ] Check nginx logs for errors

**After Deployment:**
- [ ] Run smoke tests (manual or automated)
- [ ] Monitor CloudWatch logs
- [ ] Verify frontend integration
- [ ] Update deployment documentation

---

## 11. Future Enhancements

### 11.1 Authentication & Authorization

**Requirement:** Protect API with user authentication

**Options:**
1. **API Keys:** Simple, stateless, suitable for service-to-service
2. **AWS Cognito + JWT:** User-based authentication, integrates with Amplify
3. **OAuth 2.0:** Industry standard, supports third-party integrations

**Recommended:** AWS Cognito (aligns with frontend Amplify deployment)

---

### 11.2 Caching Layer

**Requirement:** Reduce DynamoDB costs and improve response times

**Implementation:**
- **Redis/ElastiCache:** Cache discovery endpoints (sites, sectors, periods)
- **TTL:** 5-15 minutes (data rarely changes)
- **Invalidation:** Manual or event-driven (on mosaic build completion)

**Expected Impact:**
- 90% reduction in DynamoDB read costs
- 50-70% faster response times for navigation endpoints

---

### 11.3 GraphQL API

**Requirement:** Flexible data querying for frontend

**Benefits:**
- Single request for hierarchical data (site → sector → period → pad → cameras)
- Reduced over-fetching and under-fetching
- Type-safe schema with introspection

**Implementation:**
- **Framework:** Graphene-Python or Strawberry GraphQL
- **Schema:** Mirror REST endpoints as GraphQL queries
- **Resolvers:** Reuse existing service layer

---

### 11.4 Real-Time Updates

**Requirement:** Notify frontend when new mosaics are built

**Implementation:**
- **WebSockets:** Server-to-client push notifications
- **Server-Sent Events (SSE):** Simpler alternative to WebSockets
- **AWS AppSync:** Managed GraphQL with real-time subscriptions

**Use Case:**
- Frontend displays "New mosaic available" notification
- Auto-refresh pad list when processing completes

---

### 11.5 Data Versioning

**Requirement:** Track mosaic versions when reprocessed

**Implementation:**
- Add `version` or `timestamp` to S3 keys
- Store multiple versions in DynamoDB
- API parameter: `version=latest` or `version={timestamp}`

**Example:**
```
mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/v1/viewer/odm_orthophoto.tif
mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/v2/viewer/odm_orthophoto.tif
```

---

## 12. Appendices

### Appendix A: Project Structure

```
thermal-viewer-backend/
├── app.py                          # Flask application (388 lines)
├── services/
│   ├── mosaic_service.py          # Mosaic operations (316 lines)
│   ├── camera_service.py          # Camera enrichment (115 lines)
│   └── image_service.py           # Image retrieval (172 lines)
├── utils/                          # (Reserved for future)
├── scripts/
│   ├── build_and_push_backend.sh  # ECR deployment
│   └── test_viewer_backend.sh     # Automated testing
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container definition
├── docker-compose.yml              # Docker Compose config
├── README.md                       # API documentation
├── DEPLOYMENT.md                   # Deployment guide
├── TEST_PLAN.md                    # Manual test plan
├── TODO.md                         # Future enhancements
└── PRD.md                          # This document
```

---

### Appendix B: Dependencies

**requirements.txt:**
```
Flask==3.0.0
Flask-CORS==4.0.0
boto3==1.34.0
pyproj==3.6.0
```

**System Dependencies:**
```
libgdal-dev  # GDAL library for geospatial operations
```

---

### Appendix C: Environment Setup

**Local Development:**
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export AWS_REGION=ap-southeast-1
export S3_BUCKET=thermal-api-dev-storage-7ecb7171
export IMAGES_TABLE=thermal-api-dev-images-7ecb7171
export JOBS_TABLE=thermal-api-dev-jobs-7ecb7171
export PADS_TABLE=thermal-api-dev-pads-7ecb7171

# Configure AWS credentials
aws configure

# Run Flask app
python app.py
```

**Docker Development:**
```bash
# Build image
docker-compose build

# Start container
docker-compose up -d

# View logs
docker-compose logs -f backend

# Stop container
docker-compose down
```

---

### Appendix D: API Client Examples

**Python (requests):**
```python
import requests

BASE_URL = "https://dev-thermal.iabuilders.ai/viewer"

# Get sites
response = requests.get(f"{BASE_URL}/api/sites")
sites = response.json()

# Get orthomosaic URL
params = {
    'site': 'leyte',
    'sector': 'tongonan',
    'period': '20241230',
    'pad_id': 'leyte_tongonan_PAD_105',
    'mosaic_type': 'optical'
}
response = requests.get(f"{BASE_URL}/api/mosaic/orthomosaic", params=params)
data = response.json()
presigned_url = data['url']
```

**JavaScript (fetch):**
```javascript
const BASE_URL = 'https://dev-thermal.iabuilders.ai/viewer';

// Get sites
const response = await fetch(`${BASE_URL}/api/sites`);
const sites = await response.json();

// Get camera positions
const params = new URLSearchParams({
  site: 'leyte',
  sector: 'tongonan',
  period: '20241230',
  pad_id: 'leyte_tongonan_PAD_105',
  mosaic_type: 'optical'
});
const cameraResponse = await fetch(`${BASE_URL}/api/mosaic/cameras?${params}`);
const geojson = await cameraResponse.json();
```

**cURL:**
```bash
# Get sites
curl https://dev-thermal.iabuilders.ai/viewer/api/sites

# Get thermal stats
curl "https://dev-thermal.iabuilders.ai/viewer/api/thermal/leyte_tongonan_20241230_0379/stats"
```

---

## Document Metadata

**Version History:**
| Version | Date       | Author     | Changes                     |
|---------|------------|------------|-----------------------------|
| 1.0     | 2025-11-22 | Dev Team   | Initial PRD creation        |

**Related Documents:**
- Thermal Viewer Frontend PRD: `/Users/ronaldm/Code/tf-workspace/thermal-viewer-frontend/PRD.md`
- Thermal API TODO: `/Users/ronaldm/Code/tf-workspace/thermal-api/.claude/TODO.md`
- Thermal Viewer Architecture: `/Users/ronaldm/Code/tf-workspace/thermal-api/docs/THERMAL_VIEWER_ARCHITECTURE.md`

**Maintainers:**
- Backend Team: Thermal Viewer Development
- Infrastructure: DevOps Team
- Product Owner: [Name]

---

**END OF DOCUMENT**