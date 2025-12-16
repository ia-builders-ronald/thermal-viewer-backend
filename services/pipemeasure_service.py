"""
PipeMeasure Service

Service for retrieving pipe measurement data from DynamoDB.
Provides aggregate statistics and individual region measurements for anomalous pipe sections.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class PipeMeasureService:
    """
    Service for accessing pipe measurement data from DynamoDB.

    Data is stored in the measurements table with a GSI for efficient querying
    by site, sector, period, and pad_id.
    """

    def __init__(self, measurements_table):
        """
        Initialize the PipeMeasure service.

        Args:
            measurements_table: boto3 DynamoDB Table resource for measurements
        """
        self.measurements_table = measurements_table
        logger.info("PipeMeasureService initialized")

    def get_measurement(
        self,
        site: str,
        sector: str,
        period: str,
        pad_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get pipe measurement data for a specific PAD.

        Queries the measurements table using the SiteSectorPeriodPadIndex GSI
        to retrieve measurement data based on site, sector, period, and pad_id.

        Args:
            site: Site identifier (e.g., "leyte")
            sector: Sector identifier (e.g., "malitbog")
            period: Period identifier (e.g., "20250228-PMSB")
            pad_id: PAD identifier (e.g., "leyte_malitbog_PAD_msb")

        Returns:
            Dictionary containing measurement data if found, None otherwise.
            Measurement includes:
            - aggregate_stats: Total area, length, perimeter, region count
            - region_measurements: Individual anomaly region details
            - geo_bounds: Geographic boundaries
            - processing_params: Processing configuration

        Raises:
            Exception: If DynamoDB query fails
        """
        try:
            # Construct the GSI sort key
            # Format: {sector}#{period}#{pad_id}
            sector_period_pad = f"{sector}#{period}#{pad_id}"

            logger.info(
                f"Querying measurements for site={site}, "
                f"sector_period_pad={sector_period_pad}"
            )

            # Query using the GSI
            response = self.measurements_table.query(
                IndexName='SiteSectorPeriodPadIndex',
                KeyConditionExpression='site_id = :site AND sector_period_pad = :spp',
                ExpressionAttributeValues={
                    ':site': site,
                    ':spp': sector_period_pad
                },
                Limit=1  # We only expect one measurement per PAD
            )

            items = response.get('Items', [])

            if not items:
                logger.info(
                    f"No measurement found for {site}/{sector}/{period}/{pad_id}"
                )
                return None

            measurement = items[0]
            logger.info(
                f"Found measurement: {measurement.get('measurement_id')} "
                f"with {measurement.get('aggregate_stats', {}).get('total_regions', 0)} regions"
            )

            return measurement

        except Exception as e:
            logger.error(
                f"Error querying measurements for {site}/{sector}/{period}/{pad_id}: {e}",
                exc_info=True
            )
            raise

    def get_measurement_by_id(self, measurement_id: str) -> Optional[Dict[str, Any]]:
        """
        Get pipe measurement data by measurement_id (primary key).

        This is a direct lookup using the primary key, faster than querying by GSI.

        Args:
            measurement_id: Measurement ID (format: {site}_{sector}_{period}_{pad_id})

        Returns:
            Dictionary containing measurement data if found, None otherwise.

        Raises:
            Exception: If DynamoDB get_item fails
        """
        try:
            logger.info(f"Getting measurement by ID: {measurement_id}")

            response = self.measurements_table.get_item(
                Key={'measurement_id': measurement_id}
            )

            item = response.get('Item')

            if not item:
                logger.info(f"No measurement found with ID: {measurement_id}")
                return None

            logger.info(
                f"Found measurement: {measurement_id} "
                f"with {item.get('aggregate_stats', {}).get('total_regions', 0)} regions"
            )

            return item

        except Exception as e:
            logger.error(
                f"Error getting measurement by ID {measurement_id}: {e}",
                exc_info=True
            )
            raise

    def get_measurements_by_sector(
        self,
        site: str,
        sector: str,
        period: str
    ) -> List[Dict[str, Any]]:
        """
        Get all pipe measurements for a sector/period.

        Queries the measurements table using the SiteSectorPeriodPadIndex GSI
        with begins_with to retrieve all pad measurements for a given sector/period.

        Args:
            site: Site identifier (e.g., "leyte")
            sector: Sector identifier (e.g., "malitbog")
            period: Period identifier (e.g., "20250228-PMSB")

        Returns:
            List of measurement dictionaries for all pads in the sector/period.
            Each measurement includes:
            - pad_id: PAD identifier
            - aggregate_stats: Total area, length, perimeter, region count
            - geo_bounds: Geographic boundaries

        Raises:
            Exception: If DynamoDB query fails
        """
        try:
            # Construct the GSI sort key prefix for begins_with query
            # Format: {sector}#{period}#
            sector_period_prefix = f"{sector}#{period}#"

            logger.info(
                f"Querying all measurements for site={site}, "
                f"sector={sector}, period={period}"
            )

            # Query using the GSI with begins_with on sort key
            response = self.measurements_table.query(
                IndexName='SiteSectorPeriodPadIndex',
                KeyConditionExpression='site_id = :site AND begins_with(sector_period_pad, :prefix)',
                ExpressionAttributeValues={
                    ':site': site,
                    ':prefix': sector_period_prefix
                }
            )

            items = response.get('Items', [])

            # Handle pagination if there are more results
            while 'LastEvaluatedKey' in response:
                response = self.measurements_table.query(
                    IndexName='SiteSectorPeriodPadIndex',
                    KeyConditionExpression='site_id = :site AND begins_with(sector_period_pad, :prefix)',
                    ExpressionAttributeValues={
                        ':site': site,
                        ':prefix': sector_period_prefix
                    },
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                items.extend(response.get('Items', []))

            logger.info(
                f"Found {len(items)} measurements for {site}/{sector}/{period}"
            )

            return items

        except Exception as e:
            logger.error(
                f"Error querying measurements for {site}/{sector}/{period}: {e}",
                exc_info=True
            )
            raise
