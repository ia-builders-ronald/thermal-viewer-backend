"""
Camera Service
Handles camera position data from ODM outputs
"""

import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CameraService:
    """Service for camera position operations"""

    def __init__(self, s3_client, s3_bucket, images_table):
        """
        Initialize Camera Service

        Args:
            s3_client: Boto3 S3 client
            s3_bucket: S3 bucket name
            images_table: DynamoDB images table resource
        """
        self.s3 = s3_client
        self.s3_bucket = s3_bucket
        self.images_table = images_table

    def get_camera_positions(
        self,
        site: str,
        sector: str,
        period: str,
        pad_id: str,
        mosaic_type: str
    ) -> Dict:
        """
        Get camera positions as GeoJSON with enriched metadata

        Args:
            site: Site ID
            sector: Sector ID
            period: Period
            pad_id: Pad ID
            mosaic_type: Mosaic type

        Returns:
            GeoJSON FeatureCollection
        """
        # Fetch shots.geojson from S3
        s3_key = f"mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/viewer/shots.geojson"

        try:
            response = self.s3.get_object(Bucket=self.s3_bucket, Key=s3_key)
            geojson = json.loads(response['Body'].read())

            # Query images table to get image_id mapping
            image_response = self.images_table.query(
                IndexName='SiteSectorPeriodIndex',
                KeyConditionExpression='site_id = :site AND sector_period = :sp',
                FilterExpression='pad_id = :pad',
                ExpressionAttributeValues={
                    ':site': site,
                    ':sp': f"{sector}#{period}",
                    ':pad': pad_id
                }
            )

            images = {img['optical_filename']: img for img in image_response['Items']}

            # Enrich GeoJSON features with metadata
            for feature in geojson.get('features', []):
                optical_filename = feature['properties'].get('filename')

                if optical_filename in images:
                    img_record = images[optical_filename]

                    # Add image_id for API calls
                    feature['properties']['image_id'] = img_record['image_id']

                    # Add thermal filename
                    feature['properties']['thermal_filename'] = img_record.get('thermal_filename', '')

                    # Add altitude if available
                    optical_metadata = img_record.get('optical_metadata', {})
                    gps_location = optical_metadata.get('gps_location', {})
                    if 'altitude' in gps_location:
                        feature['properties']['altitude'] = float(gps_location['altitude'])

                    # Add temperature data if available
                    thermal_metadata = img_record.get('thermal_metadata', {})
                    if thermal_metadata:
                        feature['properties']['temp_max'] = float(thermal_metadata.get('temperature_max', 0))
                        feature['properties']['temp_min'] = float(thermal_metadata.get('temperature_min', 0))

            logger.info(f"Retrieved {len(geojson.get('features', []))} camera positions")
            return geojson

        except Exception as e:
            logger.error(f"Error fetching camera positions: {e}")
            raise
