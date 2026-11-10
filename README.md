# Thermal Viewer Backend

Flask REST API server for the thermal mosaic viewer frontend.

## Overview

This backend provides API endpoints for:
- Site/sector/period/pad discovery
- Mosaic orthomosaic retrieval (presigned S3 URLs)
- Camera position data (GeoJSON)
- Individual image retrieval (optical and thermal)
- Temperature statistics
- Coverage statistics

## Architecture

- **Framework**: Flask 3.0 with Flask-CORS
- **Data Storage**: AWS DynamoDB (read-only)
- **File Storage**: AWS S3 (read-only)
- **Coordinate Systems**: WGS84, UTM

## Setup

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export AWS_REGION=ap-southeast-1
export S3_BUCKET=thermal-api-dev-storage-7ecb7171
export IMAGES_TABLE=thermal-api-dev-images-7ecb7171
export JOBS_TABLE=thermal-api-dev-jobs-7ecb7171
export PADS_TABLE=thermal-api-dev-pads-7ecb7171
export COGNITO_USER_POOL_ID=ap-southeast-1_fwuioqTOs
export COGNITO_CLIENT_ID=7k3pdtsm3mq6p7tioajsgevnkn
export COGNITO_DOMAIN=ap-southeast-1fwuioqtos.auth.ap-southeast-1.amazoncognito.com
export USERS_TABLE=thermal-viewer-dev-users
```

3. Run the server:
```bash
python app.py
```

Server will start on `http://localhost:5001`

### Docker

Build and run with Docker:

```bash
docker build -t thermal-viewer-backend .
docker run -p 5001:5001 \
  -e AWS_REGION=ap-southeast-1 \
  -e S3_BUCKET=thermal-api-dev-storage-7ecb7171 \
  -e IMAGES_TABLE=thermal-api-dev-images-7ecb7171 \
  -e JOBS_TABLE=thermal-api-dev-jobs-7ecb7171 \
  -e PADS_TABLE=thermal-api-dev-pads-7ecb7171 \
  -e COGNITO_USER_POOL_ID=<pool-id> \
  -e COGNITO_CLIENT_ID=<app-client-id> \
  -e COGNITO_DOMAIN=<hosted-ui-hostname> \
  -e USERS_TABLE=<users-table> \
  -e CORS_ORIGINS=https://master.d1aqqm159oe3x8.amplifyapp.com,http://localhost:5173 \
  thermal-viewer-backend
```

## Authentication and roles

Every `/api/` endpoint requires a Cognito **access token** sent as
`Authorization: Bearer <token>` (no query-string tokens). The token must be
RS256-signed by the pool, unexpired, `token_use == "access"`, with `client_id`
matching `COGNITO_CLIENT_ID`. `/health` and `/` are public.

On the first valid request a row is created in the users table
(`USERS_TABLE`, key `sub`) with role `viewer`. A `blocked` row gets 403.

| Role | Permissions |
|------|-------------|
| `admin` | all six |
| `viewer` | `view` |
| `monitor` | `view`, `monitor_runs` |
| `operator` | `view`, `monitor_runs`, `operate_runs` |
| `geo_editor` | `view`, `edit_geo` |
| `notes` | `view`, `write_notes` |

Permissions: `view`, `admin_users`, `monitor_runs`, `operate_runs`, `edit_geo`, `write_notes`.

| Endpoint | Description |
|----------|-------------|
| `GET /api/me` | Current user: sub, username, email, name, role, permissions |
| `GET /api/admin/users` | List users (`admin_users`) |
| `PATCH /api/admin/users/<sub>` | Body `{"role": ..., "blocked": ...}` (`admin_users`) |

Error responses are JSON `{"error": "<message>", "code": "<code>"}`. Codes: 401 `unauthenticated`; 403 `blocked`
or `forbidden`; 400 `invalid`; 404 `not_found`; 409 `self` (cannot change or
block yourself) or `last_admin`; 502 `cognito`.

**Required environment** (the app refuses to start if any is missing; there is
no auth-off switch): `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`,
`COGNITO_DOMAIN` (bare hostname), `USERS_TABLE`. Optional: `COGNITO_REGION`
(default `ap-southeast-1`), `CORS_ORIGINS` (comma-separated allowed origins).

**Making the first admin:** the person signs in once (creating their row), then:

```bash
python scripts/set_role.py --email me@example.com --role admin
# or: --sub <cognito-sub>   [--table thermal-viewer-dev-users]
```

## API Endpoints

### Discovery Endpoints

#### Get Sites
```
GET /api/sites
Response: ["leyte"]
```

#### Get Sectors
```
GET /api/sectors?site=leyte
Response: ["mahanagdong-a", "mahanagdong-b", ...]
```

#### Get Periods
```
GET /api/periods?site=leyte&sector=tongonan
Response: ["20250409", "20250401", ...]
```

#### Get Pads
```
GET /api/pads?site=leyte&sector=tongonan
Response: [
  {
    "pad_id": "leyte_tongonan_PAD_401",
    "pad_name": "401",
    "geo_location_area": [...]
  }
]
```

### Mosaic Endpoints

#### Get Mosaic Metadata
```
GET /api/mosaic/metadata?site=leyte&sector=tongonan&period=20250409&pad_id=leyte_tongonan_PAD_401&mosaic_type=optical

Response: {
  "exists": true,
  "image_count": 101,
  "site": "leyte",
  "sector": "tongonan",
  "period": "20250409",
  "pad_id": "leyte_tongonan_PAD_401",
  "mosaic_type": "optical"
}
```

#### Get Orthomosaic URL
```
GET /api/mosaic/orthomosaic?site=leyte&sector=tongonan&period=20250409&pad_id=leyte_tongonan_PAD_401&mosaic_type=optical

Response: {
  "url": "https://s3.amazonaws.com/..."
}
```

#### Get Camera Positions
```
GET /api/mosaic/cameras?site=leyte&sector=tongonan&period=20250409&pad_id=leyte_tongonan_PAD_401&mosaic_type=optical

Response: {
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [124.635, 11.165, 445.5]
      },
      "properties": {
        "filename": "DJI_0380_W.JPG",
        "image_id": "leyte_tongonan_20250409_0379",
        "thermal_filename": "DJI_0381_T.JPG",
        "altitude": 445.5,
        "temp_max": 131.6,
        "temp_min": 22.7
      }
    }
  ]
}
```

### Image Endpoints

#### Get Optical Image URL
```
GET /api/optical/leyte_tongonan_20250409_0379

Response: {
  "url": "https://s3.amazonaws.com/..."
}
```

#### Get Thermal Image URL
```
GET /api/thermal/leyte_tongonan_20250409_0379?palette=medical

Response: {
  "url": "https://s3.amazonaws.com/..."
}
```

#### Get Thermal Statistics
```
GET /api/thermal/leyte_tongonan_20250409_0379/stats

Response: {
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

### Coverage Stats

```
GET /api/coverage/stats?site=leyte&sector=tongonan&period=20250409&pad_id=leyte_tongonan_PAD_401

Response: {
  "total_images": 101,
  "coverage_area_m2": 32891.45,
  "avg_altitude_m": 445.4,
  "camera_fov_deg": 68.9
}
```

## Dependencies

- Flask 3.0.0 - Web framework
- Flask-CORS 4.0.0 - CORS support for frontend
- boto3 1.34.0 - AWS SDK
- pyproj 3.6.0 - Coordinate transformations

## IAM Permissions Required

The EC2 instance running this backend needs an IAM role with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-images-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-jobs-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-pads-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-*/index/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::thermal-api-dev-storage-*/*"
    }
  ]
}
```

## Project Structure

```
thermal-viewer-backend/
├── app.py                      # Flask application with API routes
├── services/
│   ├── mosaic_service.py       # Mosaic data retrieval
│   ├── camera_service.py       # Camera position processing
│   └── image_service.py        # Image and temperature stats
├── utils/                      # Utility modules (future)
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker container definition
└── README.md                   # This file
```

## Development

### Adding New Endpoints

1. Add route handler in `app.py`
2. Implement business logic in appropriate service (`services/`)
3. Test with curl or Postman

### Error Handling

All endpoints return proper HTTP status codes:
- 200: Success
- 400: Bad request (missing parameters)
- 404: Resource not found
- 500: Server error

Errors are returned as JSON:
```json
{
  "error": "Error message"
}
```

## DynamoDB Implementation Details

### Reserved Words Handling

DynamoDB has reserved words that cannot be used directly in expressions. This backend handles the following reserved words using `ExpressionAttributeNames`:

**Reserved words used**: `site`, `sector`

**Implementation**:
```python
# Example from /api/sites endpoint
response = pads_table.scan(
    ProjectionExpression='#site',
    FilterExpression='attribute_exists(#site)',
    ExpressionAttributeNames={'#site': 'site'}
)
```

### Data Validation

Some items in the pads table may have inconsistent attribute names (e.g., `site_id` instead of `site`). The backend uses `attribute_exists()` filters to exclude invalid items:

```python
FilterExpression='attribute_exists(#site) AND attribute_exists(#sector)'
```

### Pagination Support

All scan operations support DynamoDB pagination to handle tables larger than 1MB:

```python
# Handle pagination for large tables
while 'LastEvaluatedKey' in response:
    scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    response = table.scan(**scan_kwargs)
    all_items.extend(response['Items'])
```

## Testing

### Automated Test Suite

A comprehensive test script is available at `scripts/test_viewer_backend.sh`:

```bash
./scripts/test_viewer_backend.sh
```

**Tests include**:
- Health check validation
- Data discovery endpoints (sites, sectors, periods, pads)
- Mosaic endpoints (metadata, orthomosaic URLs, camera positions)
- Image endpoints (optical, thermal, stats)
- Coverage statistics
- Error handling (400/500 responses)

See `TEST_PLAN.md` for detailed test documentation.

### Manual Testing

```bash
# Health check
curl https://dev-thermal.dabuilders.net/viewer/health

# Get sites
curl https://dev-thermal.dabuilders.net/viewer/api/sites

# Get mosaic metadata
curl "https://dev-thermal.dabuilders.net/viewer/api/mosaic/metadata?site=leyte&sector=mahanagdong-b&period=20241230&pad_id=leyte_mahanagdong-b_PAD_mgdl&mosaic_type=optical"
```

## Deployment

### Production Deployment (EC2)

**Prerequisites**:
- EC2 instance with Docker installed
- IAM role with DynamoDB and S3 read permissions (see above)
- nginx installed and configured

**1. Build and Push Docker Image**:
```bash
# Build
docker build -t thermal-viewer-backend .

# Tag for ECR
docker tag thermal-viewer-backend:latest 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend:latest

# Push to ECR
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com
docker push 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend:latest
```

**2. Deploy with docker-compose**:
```bash
# On EC2 instance
docker-compose pull
docker-compose up -d
```

**3. nginx Configuration**:

Add viewer backend proxy to nginx config:

```nginx
# Upstream for viewer backend
upstream thermal_viewer {
    server localhost:5001;
}

# Viewer Backend API
location /viewer/api/ {
    rewrite ^/viewer/api/(.*) /api/$1 break;
    proxy_pass http://thermal_viewer;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Viewer health check
location /viewer/health {
    proxy_pass http://thermal_viewer/health;
    access_log off;
}
```

**4. Verify Deployment**:
```bash
# Health check
curl https://dev-thermal.dabuilders.net/viewer/health

# Test API endpoint
curl https://dev-thermal.dabuilders.net/viewer/api/sites
```
