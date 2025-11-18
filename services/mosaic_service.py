"""
Mosaic Service
Handles mosaic data retrieval from S3 and DynamoDB
"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MosaicService:
    """Service for mosaic data operations"""

    def __init__(self, s3_client, s3_bucket, images_table, jobs_table):
        """
        Initialize Mosaic Service

        Args:
            s3_client: Boto3 S3 client
            s3_bucket: S3 bucket name
            images_table: DynamoDB images table resource
            jobs_table: DynamoDB jobs table resource
        """
        self.s3 = s3_client
        self.s3_bucket = s3_bucket
        self.images_table = images_table
        self.jobs_table = jobs_table

    def get_orthomosaic_url(
        self,
        site: str,
        sector: str,
        period: str,
        pad_id: str,
        mosaic_type: str
    ) -> str:
        """
        Generate presigned URL for orthomosaic GeoTIFF

        Args:
            site: Site ID
            sector: Sector ID
            period: Period (YYYYMMDD)
            pad_id: Pad ID
            mosaic_type: Mosaic type (optical, medical, hotspot_alert)

        Returns:
            Presigned S3 URL
        """
        s3_key = f"mosaics/{site}/{sector}/{period}/{pad_id}/{mosaic_type}/viewer/odm_orthophoto.tif"

        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.s3_bucket,
                    'Key': s3_key
                },
                ExpiresIn=3600  # 1 hour
            )
            logger.info(f"Generated orthomosaic URL for {s3_key}")
            return url
        except Exception as e:
            logger.error(f"Error generating orthomosaic URL: {e}")
            raise

    def get_mosaic_metadata(
        self,
        site: str,
        sector: str,
        period: str,
        pad_id: str,
        mosaic_type: str
    ) -> Dict:
        """
        Get mosaic job metadata and statistics

        Args:
            site: Site ID
            sector: Sector ID
            period: Period
            pad_id: Pad ID
            mosaic_type: Mosaic type

        Returns:
            Metadata dictionary
        """
        # Query images for this pad to get image count
        try:
            response = self.images_table.query(
                IndexName='SiteSectorPeriodIndex',
                KeyConditionExpression='site_id = :site AND sector_period = :sp',
                FilterExpression='pad_id = :pad',
                ExpressionAttributeValues={
                    ':site': site,
                    ':sp': f"{sector}#{period}",
                    ':pad': pad_id
                }
            )

            images = response.get('Items', [])

            # Check if mosaic exists
            mosaic_exists = False
            if images:
                # Check first image for mosaic processing status
                first_image = images[0]
                processing_status = first_image.get('processing_status', {})
                mosaic_prep = processing_status.get('mosaic_prep', {})
                mosaic_s3_keys = mosaic_prep.get('mosaic_s3_keys', {})
                mosaic_exists = mosaic_type in mosaic_s3_keys

            return {
                'exists': mosaic_exists,
                'image_count': len(images),
                'site': site,
                'sector': sector,
                'period': period,
                'pad_id': pad_id,
                'mosaic_type': mosaic_type
            }

        except Exception as e:
            logger.error(f"Error fetching mosaic metadata: {e}")
            raise

    def get_coverage_stats(
        self,
        site: str,
        sector: str,
        period: str,
        pad_id: str
    ) -> Dict:
        """
        Get coverage statistics for a pad

        Args:
            site: Site ID
            sector: Sector ID
            period: Period
            pad_id: Pad ID

        Returns:
            Coverage statistics
        """
        try:
            # Query images for this pad
            response = self.images_table.query(
                IndexName='SiteSectorPeriodIndex',
                KeyConditionExpression='site_id = :site AND sector_period = :sp',
                FilterExpression='pad_id = :pad',
                ExpressionAttributeValues={
                    ':site': site,
                    ':sp': f"{sector}#{period}",
                    ':pad': pad_id
                }
            )

            images = response.get('Items', [])

            if not images:
                return {
                    'total_images': 0,
                    'coverage_area_m2': 0,
                    'avg_altitude_m': 0,
                    'camera_fov_deg': 0
                }

            # Calculate statistics
            total_images = len(images)

            # Get average altitude from optical metadata
            altitudes = []
            for img in images:
                optical_metadata = img.get('optical_metadata', {})
                gps_location = optical_metadata.get('gps_location', {})
                altitude = gps_location.get('altitude')
                if altitude:
                    altitudes.append(float(altitude))

            avg_altitude = sum(altitudes) / len(altitudes) if altitudes else 0

            # Estimate coverage area (simplified calculation)
            # Assuming DJI M2EA with 68.9° FOV
            camera_fov = 68.9

            # Calculate ground coverage per image at average altitude
            # For simplicity, assume nadir shots
            if avg_altitude > 0:
                import math
                fov_rad = math.radians(camera_fov)
                ground_width = 2 * avg_altitude * math.tan(fov_rad / 2)
                ground_height = ground_width * (512 / 640)  # DJI thermal aspect ratio
                area_per_image = ground_width * ground_height
                # Assume 60% overlap
                total_area = area_per_image * total_images * 0.4
            else:
                total_area = 0

            return {
                'total_images': total_images,
                'coverage_area_m2': round(total_area, 2),
                'avg_altitude_m': round(avg_altitude, 2),
                'camera_fov_deg': camera_fov
            }

        except Exception as e:
            logger.error(f"Error calculating coverage stats: {e}")
            raise
