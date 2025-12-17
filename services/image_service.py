"""
Image Service
Handles image retrieval and temperature statistics
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class ImageService:
    """Service for image operations"""

    def __init__(self, s3_client, s3_bucket, images_table):
        """
        Initialize Image Service

        Args:
            s3_client: Boto3 S3 client
            s3_bucket: S3 bucket name
            images_table: DynamoDB images table resource
        """
        self.s3 = s3_client
        self.s3_bucket = s3_bucket
        self.images_table = images_table

    def get_optical_image_url(self, image_id: str) -> str:
        """
        Generate presigned URL for optical image

        Args:
            image_id: Image ID

        Returns:
            Presigned S3 URL
        """
        try:
            # Get image record from DynamoDB
            response = self.images_table.get_item(Key={'image_id': image_id})
            item = response.get('Item')

            if not item:
                raise ValueError(f"Image not found: {image_id}")

            s3_key = item.get('optical_s3_key')
            if not s3_key:
                raise ValueError(f"No optical S3 key for image: {image_id}")

            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.s3_bucket,
                    'Key': s3_key
                },
                ExpiresIn=3600  # 1 hour
            )

            logger.info(f"Generated optical image URL for {image_id}")
            return url

        except Exception as e:
            logger.error(f"Error generating optical image URL: {e}")
            raise

    def get_thermal_image_url(self, image_id: str, palette: str = 'medical') -> str:
        """
        Generate presigned URL for colored thermal image

        Args:
            image_id: Image ID
            palette: Color palette (medical or hotspot_alert)

        Returns:
            Presigned S3 URL
        """
        try:
            # Get image record from DynamoDB
            response = self.images_table.get_item(Key={'image_id': image_id})
            item = response.get('Item')

            if not item:
                raise ValueError(f"Image not found: {image_id}")

            # Get colored image S3 key
            colored_images = item.get('colored_images', {})
            s3_key = colored_images.get(palette)

            if not s3_key:
                raise ValueError(f"No {palette} thermal image for {image_id}")

            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.s3_bucket,
                    'Key': s3_key
                },
                ExpiresIn=3600  # 1 hour
            )

            logger.info(f"Generated thermal image URL ({palette}) for {image_id}")
            return url

        except Exception as e:
            logger.error(f"Error generating thermal image URL: {e}")
            raise

    def get_thermal_stats(self, image_id: str) -> Dict:
        """
        Get temperature statistics for thermal image

        Args:
            image_id: Image ID

        Returns:
            Dictionary with temperature statistics including dataset-wide temperature range
        """
        try:
            # Get image record from DynamoDB
            response = self.images_table.get_item(Key={'image_id': image_id})
            item = response.get('Item')

            if not item:
                raise ValueError(f"Image not found: {image_id}")

            thermal_metadata = item.get('thermal_metadata', {})

            # Check if image has calibration data
            calibration = item.get('calibration', {})
            is_calibrated = calibration.get('status') == 'calibrated'

            if is_calibrated:
                # Use calibrated temperatures
                temp_delta = calibration.get('temperature_delta', {})
                stats = {
                    'min_temp': float(thermal_metadata.get('temperature_min', 0)),
                    'max_temp': float(temp_delta.get('max_calibrated', 0)),
                    'avg_temp': float(temp_delta.get('avg_calibrated', 0)),
                    'is_calibrated': True,
                    'palette': 'medical',
                    'calibration_params': {
                        'emissivity': float(calibration.get('params', {}).get('emissivity', 0)),
                        'distance': float(calibration.get('params', {}).get('distance', 0)),
                        'reflection': float(calibration.get('params', {}).get('reflection', 0)),
                        'ambient_temp': float(calibration.get('params', {}).get('ambient_temp', 0)),
                        'humidity': float(calibration.get('params', {}).get('humidity', 0))
                    }
                }
            else:
                # Use original temperatures
                stats = {
                    'min_temp': float(thermal_metadata.get('temperature_min', 0)),
                    'max_temp': float(thermal_metadata.get('temperature_max', 0)),
                    'avg_temp': float(thermal_metadata.get('temperature_avg', 0)),
                    'is_calibrated': False,
                    'palette': 'medical',
                    'original_params': {
                        'emissivity': float(thermal_metadata.get('emissivity', 0)),
                        'distance': float(thermal_metadata.get('object_distance', 0)),
                        'reflection': float(thermal_metadata.get('reflected_temperature', 0)),
                        'ambient_temp': float(thermal_metadata.get('ambient_temperature', 0)),
                        'humidity': float(thermal_metadata.get('relative_humidity', 0))
                    }
                }

            # Extract dataset-wide temperature range from colormapping metadata
            processing_status = item.get('processing_status')
            if processing_status:
                colormapping = processing_status.get('colormapping')
                if colormapping:
                    medical_palette = colormapping.get('medical')
                    if medical_palette:
                        temperature_stats = medical_palette.get('temperature_stats')
                        if temperature_stats:
                            stats['dataset_temperature_range'] = {
                                'min_temp_c': float(temperature_stats.get('min_temp_c', 0)),
                                'max_temp_c': float(temperature_stats.get('max_temp_c', 0)),
                                'mean_temp_c': float(temperature_stats.get('mean_temp_c', 0)),
                                'normalization': temperature_stats.get('normalization', 'unknown'),
                                'sample_size': int(temperature_stats.get('sample_size', 0))
                            }
                            logger.info(f"Retrieved dataset temperature range for {image_id}: "
                                      f"{stats['dataset_temperature_range']['min_temp_c']:.1f} - "
                                      f"{stats['dataset_temperature_range']['max_temp_c']:.1f} °C")

            logger.info(f"Retrieved thermal stats for {image_id} (calibrated: {is_calibrated})")
            return stats

        except Exception as e:
            logger.error(f"Error fetching thermal stats: {e}")
            raise
