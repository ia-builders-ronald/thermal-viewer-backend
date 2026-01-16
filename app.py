"""
Thermal Viewer Backend API
Flask server providing REST endpoints for thermal mosaic viewer
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import os
import io
import logging
from decimal import Decimal

from services.mosaic_service import MosaicService
from services.camera_service import CameraService
from services.image_service import ImageService
from services.pipemeasure_service import PipeMeasureService
from services.report_service import ReportService
from middleware.auth import require_auth, init_auth

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Configuration from environment variables
AWS_REGION = os.environ.get('AWS_REGION', 'ap-southeast-1')
S3_BUCKET = os.environ.get('S3_BUCKET', 'thermal-api-dev-storage-7ecb7171')
IMAGES_TABLE = os.environ.get('IMAGES_TABLE', 'thermal-api-dev-images-7ecb7171')
JOBS_TABLE = os.environ.get('JOBS_TABLE', 'thermal-api-dev-jobs-7ecb7171')
PADS_TABLE = os.environ.get('PADS_TABLE', 'thermal-api-dev-pads-7ecb7171')
MEASUREMENTS_TABLE = os.environ.get('MEASUREMENTS_TABLE', 'thermal-api-dev-measurements-7ecb7171')

# Initialize AWS clients
s3_client = boto3.client('s3', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
images_table = dynamodb.Table(IMAGES_TABLE)
jobs_table = dynamodb.Table(JOBS_TABLE)
pads_table = dynamodb.Table(PADS_TABLE)
measurements_table = dynamodb.Table(MEASUREMENTS_TABLE)

# Initialize services
mosaic_service = MosaicService(s3_client, S3_BUCKET, images_table, jobs_table)
camera_service = CameraService(s3_client, S3_BUCKET, images_table)
image_service = ImageService(s3_client, S3_BUCKET, images_table)
pipemeasure_service = PipeMeasureService(measurements_table)
report_service = ReportService(
    template_path=os.path.join(os.path.dirname(__file__), 'templates', 'line-loss-template.docx')
)

# Initialize authentication
init_auth(app)


# Helper function to convert Decimal to float for JSON serialization
def decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(item) for item in obj]
    return obj


# ============================================================================
# DATA DISCOVERY ENDPOINTS
# ============================================================================

@app.route('/api/sites', methods=['GET'])
@require_auth
def get_sites():
    """Get list of all sites"""
    try:
        # Scan pads table for unique sites, excluding items without 'site' attribute
        all_items = []
        scan_kwargs = {
            'ProjectionExpression': '#site',
            'FilterExpression': 'attribute_exists(#site)',
            'ExpressionAttributeNames': {'#site': 'site'}
        }

        # Handle pagination
        response = pads_table.scan(**scan_kwargs)
        all_items.extend(response['Items'])

        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = pads_table.scan(**scan_kwargs)
            all_items.extend(response['Items'])

        # Extract unique sites
        sites = sorted(list(set(item['site'] for item in all_items)))
        return jsonify(sites)
    except Exception as e:
        logger.error(f"Error fetching sites: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sectors', methods=['GET'])
@require_auth
def get_sectors():
    """Get list of sectors for a site"""
    site = request.args.get('site')
    if not site:
        return jsonify({'error': 'site parameter required'}), 400

    try:
        # Scan pads table for sectors in this site
        all_items = []
        scan_kwargs = {
            'FilterExpression': '#site = :site AND attribute_exists(#sector)',
            'ExpressionAttributeNames': {
                '#site': 'site',
                '#sector': 'sector'
            },
            'ExpressionAttributeValues': {':site': site},
            'ProjectionExpression': '#sector'
        }

        # Handle pagination
        response = pads_table.scan(**scan_kwargs)
        all_items.extend(response['Items'])

        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = pads_table.scan(**scan_kwargs)
            all_items.extend(response['Items'])

        # Extract unique sectors
        sectors = sorted(list(set(item['sector'] for item in all_items)))
        return jsonify(sectors)
    except Exception as e:
        logger.error(f"Error fetching sectors: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/periods', methods=['GET'])
@require_auth
def get_periods():
    """Get list of periods for a site and sector"""
    site = request.args.get('site')
    sector = request.args.get('sector')

    if not site or not sector:
        return jsonify({'error': 'site and sector parameters required'}), 400

    try:
        # Query images table for periods
        response = images_table.scan(
            FilterExpression='site_id = :site AND sector_id = :sector',
            ExpressionAttributeValues={
                ':site': site,
                ':sector': sector
            },
            ProjectionExpression='period'
        )
        periods = list(set(item['period'] for item in response['Items']))
        periods.sort(reverse=True)  # Most recent first

        return jsonify(periods)
    except Exception as e:
        logger.error(f"Error fetching periods: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/pads', methods=['GET'])
@require_auth
def get_pads():
    """Get list of pads for a site and sector (filtered by completeness)"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')  # Optional: filter by completeness for this period

    if not site or not sector:
        return jsonify({'error': 'site and sector parameters required'}), 400

    try:
        # Query pads table
        response = pads_table.query(
            IndexName='SiteSectorDateIndex',
            KeyConditionExpression='site_sector = :ss',
            ExpressionAttributeValues={':ss': f"{site}_{sector}"}
        )

        pads = [{
            'pad_id': item['pad_id'],
            'pad_name': item.get('pad_name', item['pad_id'].split('_PAD_')[-1]),
            'geo_location_area': decimal_to_float(item.get('geo_location_area', []))
        } for item in response['Items']]

        # Debug: Log what pads were returned by the query
        logger.info(f"Pads from table query: {[p['pad_id'] for p in pads]}")

        # Filter by completeness if period is provided
        if period:
            logger.info(f"Filtering pads for completeness: {site}/{sector}/{period}")
            complete_pads = []
            for pad in pads:
                is_complete = mosaic_service.check_pad_completeness(
                    site, sector, period, pad['pad_id']
                )
                if is_complete:
                    complete_pads.append(pad)
                else:
                    logger.debug(f"Filtered out incomplete pad: {pad['pad_id']}")
            pads = complete_pads
            logger.info(f"Returning {len(pads)} complete pads (filtered from {len(response['Items'])} total)")

        # Sort by pad_name
        pads.sort(key=lambda x: x['pad_name'])

        return jsonify(pads)
    except Exception as e:
        logger.error(f"Error fetching pads: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# MOSAIC VIEWER ENDPOINTS
# ============================================================================

@app.route('/api/mosaic/metadata', methods=['GET'])
@require_auth
def get_mosaic_metadata():
    """Get mosaic job metadata and statistics"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')
    pad_id = request.args.get('pad_id')
    mosaic_type = request.args.get('mosaic_type', 'optical')

    if not all([site, sector, period, pad_id]):
        return jsonify({'error': 'site, sector, period, and pad_id required'}), 400

    try:
        metadata = mosaic_service.get_mosaic_metadata(
            site, sector, period, pad_id, mosaic_type
        )
        return jsonify(decimal_to_float(metadata))
    except Exception as e:
        logger.error(f"Error fetching mosaic metadata: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/mosaic/orthomosaic', methods=['GET'])
@require_auth
def get_orthomosaic_url():
    """Get presigned URL for orthomosaic GeoTIFF"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')
    pad_id = request.args.get('pad_id')
    mosaic_type = request.args.get('mosaic_type', 'optical')

    if not all([site, sector, period, pad_id]):
        return jsonify({'error': 'site, sector, period, and pad_id required'}), 400

    try:
        url = mosaic_service.get_orthomosaic_url(
            site, sector, period, pad_id, mosaic_type
        )
        return jsonify({'url': url})
    except Exception as e:
        logger.error(f"Error generating orthomosaic URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/mosaic/cameras', methods=['GET'])
@require_auth
def get_cameras():
    """Get camera positions as GeoJSON"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')
    pad_id = request.args.get('pad_id')
    mosaic_type = request.args.get('mosaic_type', 'optical')

    if not all([site, sector, period, pad_id]):
        return jsonify({'error': 'site, sector, period, and pad_id required'}), 400

    try:
        geojson = camera_service.get_camera_positions(
            site, sector, period, pad_id, mosaic_type
        )
        return jsonify(geojson)
    except Exception as e:
        logger.error(f"Error fetching camera positions: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# IMAGE ENDPOINTS
# ============================================================================

@app.route('/api/optical/<image_id>', methods=['GET'])
@require_auth
def get_optical_image(image_id):
    """Get presigned URL for optical image"""
    try:
        url = image_service.get_optical_image_url(image_id)
        return jsonify({'url': url})
    except Exception as e:
        logger.error(f"Error generating optical image URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/thermal/<image_id>', methods=['GET'])
@require_auth
def get_thermal_image(image_id):
    """Get presigned URL for colored thermal image"""
    palette = request.args.get('palette', 'medical')

    try:
        url = image_service.get_thermal_image_url(image_id, palette)
        return jsonify({'url': url})
    except Exception as e:
        logger.error(f"Error generating thermal image URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/thermal/<image_id>/stats', methods=['GET'])
@require_auth
def get_thermal_stats(image_id):
    """Get temperature statistics for thermal image"""
    try:
        stats = image_service.get_thermal_stats(image_id)
        return jsonify(decimal_to_float(stats))
    except Exception as e:
        logger.error(f"Error fetching thermal stats: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# COVERAGE STATS ENDPOINT
# ============================================================================

@app.route('/api/coverage/stats', methods=['GET'])
@require_auth
def get_coverage_stats():
    """Get coverage statistics for a mosaic"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')
    pad_id = request.args.get('pad_id')

    if not all([site, sector, period, pad_id]):
        return jsonify({'error': 'site, sector, period, and pad_id required'}), 400

    try:
        stats = mosaic_service.get_coverage_stats(site, sector, period, pad_id)
        return jsonify(decimal_to_float(stats))
    except Exception as e:
        logger.error(f"Error fetching coverage stats: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# PIPEMEASURE ENDPOINTS
# ============================================================================

@app.route('/api/pipemeasure/measurement/<site>/<sector>/<period>/<pad_id>', methods=['GET'])
@require_auth
def get_pipe_measurement(site, sector, period, pad_id):
    """
    Get pipe measurement data for a specific PAD.

    Retrieves aggregate statistics and individual region measurements for
    anomalous pipe sections detected in thermal mosaics.

    Args:
        site: Site identifier (e.g., "leyte")
        sector: Sector identifier (e.g., "malitbog")
        period: Period identifier (e.g., "20250228-PMSB")
        pad_id: PAD identifier (e.g., "leyte_malitbog_PAD_msb")

    Returns:
        JSON response with measurement data if found, 404 if not found

    Example:
        GET /api/pipemeasure/measurement/leyte/malitbog/20250228-PMSB/leyte_malitbog_PAD_msb
    """
    try:
        measurement = pipemeasure_service.get_measurement(site, sector, period, pad_id)

        if measurement is None:
            return jsonify({
                'error': 'Measurement not found',
                'message': f'No measurement data available for PAD: {pad_id}'
            }), 404

        return jsonify(decimal_to_float(measurement))

    except Exception as e:
        logger.error(f"Error fetching pipe measurement for {site}/{sector}/{period}/{pad_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/pipemeasure/measurements/<site>/<sector>/<period>', methods=['GET'])
@require_auth
def get_sector_measurements(site, sector, period):
    """
    Get all pipe measurements for a sector/period.

    Retrieves measurements for all PADs in a given sector and period.
    Used for generating Line Loss Analytics Reports.

    Args:
        site: Site identifier (e.g., "leyte")
        sector: Sector identifier (e.g., "malitbog")
        period: Period identifier (e.g., "20250228-PMSB")

    Returns:
        JSON response with list of measurements for all pads in sector/period

    Example:
        GET /api/pipemeasure/measurements/leyte/malitbog/20250228-PMSB
    """
    try:
        measurements = pipemeasure_service.get_measurements_by_sector(site, sector, period)

        return jsonify({
            'site': site,
            'sector': sector,
            'period': period,
            'count': len(measurements),
            'measurements': decimal_to_float(measurements)
        })

    except Exception as e:
        logger.error(f"Error fetching sector measurements for {site}/{sector}/{period}: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# REPORT GENERATION ENDPOINTS
# ============================================================================

@app.route('/api/report/generate', methods=['POST'])
@require_auth
def generate_report():
    """
    Generate Line Loss Analytics PDF report.

    Receives report data from frontend, fills Word template with data,
    converts to PDF using LibreOffice, and returns the PDF file.

    Request Body (JSON):
        {
            "site": "EDC",
            "sector": "MAHANAGDONG",
            "rows": [
                {"section": "Pad 101", "length": "1.50"},
                {"section": "Pad 102", "length": "N/A"}
            ]
        }

    Returns:
        PDF file as attachment

    Example:
        POST /api/report/generate
        Content-Type: application/json
        {"site": "EDC", "sector": "TEST", "rows": [...]}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required = ['site', 'sector', 'rows']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({'error': f'Missing required fields: {missing}'}), 400

        # Validate rows structure
        if not isinstance(data['rows'], list):
            return jsonify({'error': 'rows must be an array'}), 400

        logger.info(f"Generating report for {data['site']}/{data['sector']} with {len(data['rows'])} rows")

        # Generate PDF
        pdf_bytes = report_service.generate_pdf(data)

        # Return PDF file
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"line-loss-report-{data['sector']}.pdf"
        )

    except FileNotFoundError as e:
        logger.error(f"Template file not found: {e}")
        return jsonify({'error': 'Report template not found. Please contact administrator.'}), 500
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'thermal-viewer-backend',
        'version': '1.0.0'
    })


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        'service': 'Thermal Viewer Backend API',
        'version': '1.0.0',
        'endpoints': {
            'discovery': [
                '/api/sites',
                '/api/sectors?site={site}',
                '/api/periods?site={site}&sector={sector}',
                '/api/pads?site={site}&sector={sector}'
            ],
            'mosaic': [
                '/api/mosaic/metadata',
                '/api/mosaic/orthomosaic',
                '/api/mosaic/cameras'
            ],
            'images': [
                '/api/optical/{image_id}',
                '/api/thermal/{image_id}?palette={palette}',
                '/api/thermal/{image_id}/stats'
            ],
            'stats': [
                '/api/coverage/stats'
            ],
            'reports': [
                '/api/report/generate (POST)'
            ]
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Starting Thermal Viewer Backend on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
