"""
Thermal Viewer Backend API
Flask server providing REST endpoints for thermal mosaic viewer
"""

from flask import Flask, jsonify, request, send_file, g
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import os
import io
import logging
import concurrent.futures
from decimal import Decimal

from services.mosaic_service import MosaicService
from services.camera_service import CameraService
from services.image_service import ImageService
from services.pipemeasure_service import PipeMeasureService
from services.report_service import ReportService
from middleware.auth import require_auth, require_permission, init_auth
from middleware.users import ROLES

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Max parallel workers for per-pad completeness checks
PAD_COMPLETENESS_MAX_WORKERS = 16

# Initialize Flask app
app = Flask(__name__)
CORS(
    app,
    origins=[o.strip() for o in os.environ.get(
        'CORS_ORIGINS',
        'https://master.d1aqqm159oe3x8.amplifyapp.com,http://localhost:5173',
    ).split(',') if o.strip()],
    allow_headers=['Authorization', 'Content-Type'],
    methods=['GET', 'POST', 'PATCH', 'OPTIONS'],
    max_age=600,
)

# Single source of truth for the backend version (SemVer). Bump on each
# shippable change: PATCH = fix, MINOR = feature, MAJOR = breaking. Overridable
# via the APP_VERSION env var for CI-injected builds. Surfaced on /health and /
# for ops; see CHANGELOG.md for history.
APP_VERSION = os.environ.get('APP_VERSION', '1.4.0')

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


@app.route('/api/me', methods=['GET'])
@require_auth
def me():
    """Current user: refresh email/name from userInfo and record the sign-in."""
    ext = app.extensions['auth']
    info = ext['userinfo_fetcher'](ext['config'], g.user['access_token'])
    row = ext['store'].record_sign_in(g.user['sub'], email=info.get('email'), name=info.get('name'))
    return jsonify({
        'sub': g.user['sub'],
        'username': g.user['username'],
        'email': row.get('email'),
        'name': row.get('name'),
        'role': g.user['role'],
        'permissions': g.user['permissions'],
    })


_ADMIN_USER_FIELDS = ('sub', 'username', 'email', 'name', 'role', 'blocked', 'last_sign_in', 'created_at')


def _admin_user_view(row):
    return {k: row.get(k) for k in _ADMIN_USER_FIELDS}


def _admin_error(message, code, status):
    return jsonify({'error': message, 'code': code}), status


@app.route('/api/admin/users', methods=['GET'])
@require_auth
@require_permission('admin_users')
def admin_users():
    return jsonify({'users': [_admin_user_view(u) for u in app.extensions['auth']['store'].list_users()]})


@app.route('/api/admin/users/<sub>', methods=['PATCH'])
@require_auth
@require_permission('admin_users')
def admin_update_user(sub):
    """Change a user's role and/or blocked flag (blocked also disables the Cognito user)."""
    ext = app.extensions['auth']
    store, cognito = ext['store'], ext['cognito_admin']
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not (set(body) & {'role', 'blocked'}) or set(body) - {'role', 'blocked'}:
        return _admin_error('Body must contain role and/or blocked.', 'invalid', 400)
    role, blocked = body.get('role'), body.get('blocked')
    if 'role' in body and role not in ROLES:
        return _admin_error('Unknown role.', 'invalid', 400)
    if 'blocked' in body and not isinstance(blocked, bool):
        return _admin_error('blocked must be a boolean.', 'invalid', 400)

    actor = g.user['sub']
    if sub == actor:
        return _admin_error('You cannot change your own access.', 'self', 409)
    old = store.get(sub)
    if old is None:
        return _admin_error('User not found.', 'not_found', 404)

    old_role, old_blocked = old.get('role'), bool(old.get('blocked'))
    demotes = 'role' in body and role != 'admin'
    if old_role == 'admin' and not old_blocked and (demotes or blocked is True) \
            and store.count_admins() <= 1:
        return _admin_error('At least one active admin is required.', 'last_admin', 409)

    try:
        updated = store.update(sub, role=role, blocked=blocked, updated_by=actor)
    except KeyError:
        return _admin_error('User not found.', 'not_found', 404)

    # blocked:false always re-enables (idempotent) to repair any Cognito/table drift.
    if blocked is True and not old_blocked or blocked is False:
        try:
            if blocked:
                cognito.disable(old['username'])
            else:
                cognito.enable(old['username'])
        except Exception as e:
            logger.error(f"Cognito update failed for {sub}: {e}")
            if blocked:
                # disable may have succeeded before sign-out failed: best-effort undo
                try:
                    cognito.enable(old['username'])
                except Exception as undo_error:
                    logger.error(f"Cognito undo-disable failed for {sub}: {undo_error}")
            try:
                store.update(sub, role=old_role, blocked=old_blocked, updated_by=actor)
            except Exception as rollback_error:
                logger.error(f"Rollback failed for {sub}: {rollback_error}")
            return _admin_error('Could not update the sign-in service.', 'cognito', 502)

    logger.info(
        f"admin_change actor={actor} target={sub} role={old_role}->{updated.get('role')} "
        f"blocked={old_blocked}->{bool(updated.get('blocked'))}"
    )
    return jsonify(_admin_user_view(updated))


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

@app.route('/api/navigation', methods=['GET'])
@require_auth
@require_permission('view')
def get_navigation():
    """Get full site → sector → periods (+ pads) hierarchy in one call for preloading dropdowns"""
    try:
        # Step 1: Scan pads table for all site/sector pairs, plus pad identity/geo.
        # The pads table is period-independent (one row per pad per sector) and is
        # the authoritative source for the pad list.
        all_pad_items = []
        scan_kwargs = {
            'ProjectionExpression': '#site, #sector, pad_id, pad_name, geo_location_area',
            'FilterExpression': 'attribute_exists(#site) AND attribute_exists(#sector)',
            'ExpressionAttributeNames': {'#site': 'site', '#sector': 'sector'}
        }
        response = pads_table.scan(**scan_kwargs)
        all_pad_items.extend(response['Items'])
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = pads_table.scan(**scan_kwargs)
            all_pad_items.extend(response['Items'])

        # Build site → sectors map, and (site, sector) → pads map
        site_sectors: dict[str, set[str]] = {}
        sector_pads: dict[tuple[str, str], dict[str, dict]] = {}
        for item in all_pad_items:
            site = item['site']
            sector = item['sector']
            if site not in site_sectors:
                site_sectors[site] = set()
            site_sectors[site].add(sector)

            pad_id = item.get('pad_id')
            if not pad_id:
                continue
            key = (site, sector)
            if key not in sector_pads:
                sector_pads[key] = {}
            sector_pads[key][pad_id] = {
                'pad_name': item.get('pad_name', pad_id.split('_PAD_')[-1]),
                'geo_location_area': decimal_to_float(item.get('geo_location_area', [])),
            }

        # Step 2: Scan images table for all site/sector/period/pad combinations
        all_image_items = []
        scan_kwargs = {
            'ProjectionExpression': 'site_id, sector_id, period, pad_id',
            'FilterExpression': 'attribute_exists(site_id) AND attribute_exists(period)'
        }
        response = images_table.scan(**scan_kwargs)
        all_image_items.extend(response['Items'])
        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = images_table.scan(**scan_kwargs)
            all_image_items.extend(response['Items'])

        # Build site → sector → periods map, and (site, sector, pad_id) → periods map
        periods_map: dict[str, dict[str, set[str]]] = {}
        pad_periods_map: dict[tuple[str, str, str], set[str]] = {}
        for item in all_image_items:
            site = item.get('site_id', '')
            sector = item.get('sector_id', '')
            period = item.get('period', '')
            if not site or not sector or not period:
                continue
            if site not in periods_map:
                periods_map[site] = {}
            if sector not in periods_map[site]:
                periods_map[site][sector] = set()
            periods_map[site][sector].add(period)

            pad_id = item.get('pad_id', '')
            if not pad_id:
                continue
            pad_key = (site, sector, pad_id)
            if pad_key not in pad_periods_map:
                pad_periods_map[pad_key] = set()
            pad_periods_map[pad_key].add(period)

        # Step 3: Build response hierarchy
        navigation = {}
        for site in sorted(site_sectors.keys()):
            sectors = {}
            for sector in sorted(site_sectors[site]):
                periods = sorted(
                    periods_map.get(site, {}).get(sector, set()),
                    reverse=True  # Most recent first
                )

                pads = {}
                for pad_id, pad_info in sector_pads.get((site, sector), {}).items():
                    pad_periods = sorted(
                        pad_periods_map.get((site, sector, pad_id), set()),
                        reverse=True  # Most recent first
                    )
                    if not pad_periods:
                        # Exclude pads with no imagery for any period - nothing to view
                        continue
                    pads[pad_id] = {
                        'pad_name': pad_info['pad_name'],
                        'geo_location_area': pad_info['geo_location_area'],
                        'periods': pad_periods,
                    }
                # Sort pads by pad_name for stable output
                pads = dict(sorted(pads.items(), key=lambda kv: kv[1]['pad_name']))

                sectors[sector] = {'periods': periods, 'pads': pads}
            navigation[site] = {'sectors': sectors}

        return jsonify(navigation)
    except Exception as e:
        logger.error(f"Error fetching navigation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sites', methods=['GET'])
@require_auth
@require_permission('view')
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
@require_permission('view')
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
@require_permission('view')
def get_periods():
    """Get list of periods for a site and sector"""
    site = request.args.get('site')
    sector = request.args.get('sector')

    if not site or not sector:
        return jsonify({'error': 'site and sector parameters required'}), 400

    try:
        # Query images table for periods (with pagination)
        all_items = []
        scan_kwargs = {
            'FilterExpression': 'site_id = :site AND sector_id = :sector',
            'ExpressionAttributeValues': {
                ':site': site,
                ':sector': sector
            },
            'ProjectionExpression': 'period'
        }
        while True:
            response = images_table.scan(**scan_kwargs)
            all_items.extend(response['Items'])
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']

        periods = list(set(item['period'] for item in all_items))
        periods.sort(reverse=True)  # Most recent first

        return jsonify(periods)
    except Exception as e:
        logger.error(f"Error fetching periods: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/pads', methods=['GET'])
@require_auth
@require_permission('view')
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
            logger.info(f"Filtering pads for completeness: {site}/{sector}/{period} ({len(pads)} pads, max_workers={PAD_COMPLETENESS_MAX_WORKERS})")
            # Run per-pad checks in parallel; boto3 clients/tables are thread-safe for reads.
            # Preserve input order and filter semantics: include only pads whose check returns True.
            with concurrent.futures.ThreadPoolExecutor(max_workers=PAD_COMPLETENESS_MAX_WORKERS) as executor:
                future_to_pad = {
                    executor.submit(
                        mosaic_service.check_pad_completeness,
                        site, sector, period, pad['pad_id']
                    ): pad
                    for pad in pads
                }
                # Collect results keyed by pad to preserve original list order below
                completeness: dict = {}
                for future in concurrent.futures.as_completed(future_to_pad):
                    pad = future_to_pad[future]
                    try:
                        completeness[pad['pad_id']] = future.result()
                    except Exception as exc:
                        logger.warning(f"Completeness check raised for {pad['pad_id']}: {exc}; treating as incomplete")
                        completeness[pad['pad_id']] = False
            complete_pads = []
            for pad in pads:
                if completeness.get(pad['pad_id'], False):
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
@require_permission('view')
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
@require_permission('view')
def get_orthomosaic_url():
    """Get presigned URL for orthomosaic GeoTIFF"""
    site = request.args.get('site')
    sector = request.args.get('sector')
    period = request.args.get('period')
    pad_id = request.args.get('pad_id')
    mosaic_type = request.args.get('mosaic_type', 'optical')
    download = request.args.get('download', 'false').lower() == 'true'

    if not all([site, sector, period, pad_id]):
        return jsonify({'error': 'site, sector, period, and pad_id required'}), 400

    try:
        url = mosaic_service.get_orthomosaic_url(
            site, sector, period, pad_id, mosaic_type, download=download
        )
        return jsonify({'url': url})
    except Exception as e:
        logger.error(f"Error generating orthomosaic URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/mosaic/cameras', methods=['GET'])
@require_auth
@require_permission('view')
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
@require_permission('view')
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
@require_permission('view')
def get_thermal_image(image_id):
    """Get presigned URL for colored thermal image and colorbar"""
    palette = request.args.get('palette', 'medical')

    try:
        result = image_service.get_thermal_image_url(image_id, palette)
        # result contains 'url' and 'colorbar_url' (may be None)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error generating thermal image URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/thermal/<image_id>/stats', methods=['GET'])
@require_auth
@require_permission('view')
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
@require_permission('view')
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
@require_permission('view')
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
@require_permission('view')
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
# REPORT ENDPOINTS
# ============================================================================

@app.route('/api/report/<site>/<sector>/<period>', methods=['GET'])
@require_auth
@require_permission('view')
def get_report(site, sector, period):
    """
    Get presigned URLs for pre-generated reports.

    Reports are pre-generated by the thermal-api Report Agent after
    PipeMeasure processing completes. This endpoint returns presigned
    URLs for direct download from S3.

    Args:
        site: Site identifier (e.g., "leyte")
        sector: Sector identifier (e.g., "tongonan")
        period: Period identifier (e.g., "20250407-TGN-SS2")

    Returns:
        JSON with presigned URLs for PDF and CSV reports

    Example:
        GET /api/report/leyte/tongonan/20250407-TGN-SS2
        Response: {
            "pdf_url": "https://s3...",
            "csv_url": "https://s3...",
            "visual_pdf_url": "https://s3..." (optional),
            "site": "leyte",
            "sector": "tongonan",
            "period": "20250407-TGN-SS2"
        }
    """
    try:
        base_path = f"outputs/{site}/{sector}/{period}/reports"
        pdf_key = f"{base_path}/line-loss-report.pdf"
        csv_key = f"{base_path}/line-loss-report.csv"
        visual_pdf_key = f"{base_path}/line-loss-visual-report.pdf"

        # Check if PDF exists
        try:
            s3_client.head_object(Bucket=S3_BUCKET, Key=pdf_key)
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return jsonify({
                    'error': 'Report not found',
                    'message': f'No report available for {site}/{sector}/{period}. Reports are generated after PipeMeasure processing completes.'
                }), 404
            raise

        # Generate presigned URLs (1 hour expiration)
        pdf_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': pdf_key},
            ExpiresIn=3600
        )

        csv_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': csv_key},
            ExpiresIn=3600
        )

        # Check if visual PDF exists (optional - may not exist for older datasets)
        visual_pdf_url = None
        try:
            s3_client.head_object(Bucket=S3_BUCKET, Key=visual_pdf_key)
            visual_pdf_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET, 'Key': visual_pdf_key},
                ExpiresIn=3600
            )
            logger.info(f"Visual PDF available for: {site}/{sector}/{period}")
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.debug(f"No visual PDF for: {site}/{sector}/{period}")
            else:
                raise

        logger.info(f"Generated presigned URLs for report: {site}/{sector}/{period}")

        response_data = {
            'pdf_url': pdf_url,
            'csv_url': csv_url,
            'site': site,
            'sector': sector,
            'period': period
        }

        if visual_pdf_url:
            response_data['visual_pdf_url'] = visual_pdf_url

        return jsonify(response_data)

    except ClientError as e:
        logger.error(f"S3 error fetching report for {site}/{sector}/{period}: {e}")
        return jsonify({'error': 'Failed to retrieve report'}), 500
    except Exception as e:
        logger.error(f"Error fetching report for {site}/{sector}/{period}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/generate', methods=['POST'])
@require_auth
@require_permission('view')
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
        'version': APP_VERSION
    })


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        'service': 'Thermal Viewer Backend API',
        'version': APP_VERSION,
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
                '/api/report/{site}/{sector}/{period}',
                '/api/report/generate (POST)'
            ]
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Starting Thermal Viewer Backend on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
