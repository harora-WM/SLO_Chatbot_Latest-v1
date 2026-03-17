"""Data loader for parsing and loading JSON logs into DuckDB."""

import pandas as pd
from typing import Dict, List, Any
from utils.logger import setup_logger
from data.database.duckdb_manager import DuckDBManager

logger = setup_logger(__name__)


class DataLoader:
    """Loader for service and error logs."""

    def __init__(self, db_manager: DuckDBManager):
        """Initialize data loader.

        Args:
            db_manager: DuckDB manager instance
        """
        self.db_manager = db_manager

    def load_service_logs_from_platform_api(self, api_response: List[Dict[str, Any]]):
        """Load service logs from Platform API response.

        Handles the Platform API response format. Platform API returns pre-calculated
        metrics including burn rate, health indicators, aspirational SLO metrics, and
        timeliness tracking.

        Args:
            api_response: List of service health dicts from Platform API

        Returns:
            Tuple of (eb_df, response_df) DataFrames split by dataCategory
        """
        logger.info(f"Loading {len(api_response)} service records from Platform API")

        records = []
        for idx, item in enumerate(api_response):
            try:
                # Skip if noDataFound flag is set
                if item.get('noDataFound') == True:
                    logger.debug(f"Skipping record {idx}: noDataFound=True")
                    continue

                # Extract avgPercentiles nested dict
                percentiles = item.get('avgPercentiles', {})

                # Build comprehensive record with all 90+ fields
                record = {
                    # Core identifiers (5 columns)
                    'id': str(item.get('key', f"platform_{item.get('transactionId', idx)}")),
                    'app_id': None,  # Not provided by Platform API
                    'sid': item.get('transactionId'),
                    'service_name': item.get('transactionName', 'Unknown'),
                    'record_time': pd.Timestamp.now(),  # Platform API doesn't return per-record timestamp

                    # Request volume & success metrics (6 columns)
                    'total_count': int(item.get('totalCount', 0)),
                    'success_count': int(item.get('successCount', 0)),
                    'error_count': int(item.get('errorCount', 0)),
                    'success_rate': float(item.get('successRate', 0.0)),
                    'error_rate': float(item.get('errorRate', 0.0)),
                    'total_data_points': float(item.get('totalDataPoints', 0.0)),

                    # Response time metrics (11 columns)
                    'response_time_avg': float(item.get('avgResponseTime', 0.0)),
                    'response_time_min': float(percentiles.get('25.0', 0.0)),  # Use P25 as proxy for min
                    'response_time_max': float(item.get('sumResponseTime', 0.0) / max(item.get('totalCount', 1), 1)),
                    'response_time_p25': float(percentiles.get('25.0', 0.0)),
                    'response_time_p50': float(percentiles.get('50.0', 0.0)),
                    'response_time_p75': float(percentiles.get('75.0', 0.0)),
                    'response_time_p80': float(percentiles.get('80.0', 0.0)),
                    'response_time_p85': float(percentiles.get('85.0', 0.0)),
                    'response_time_p90': float(percentiles.get('90.0', 0.0)),
                    'response_time_p95': float(percentiles.get('95.0', 0.0)),
                    'response_time_p99': float(percentiles.get('99.0', 0.0)),

                    # Standard SLO targets (3 columns)
                    'target_error_slo_perc': float(item.get('shortTargetSLO', 98.0)),
                    'target_response_slo_sec': float(item.get('responseSlo', 1.0)),
                    'response_target_percent': float(item.get('responseTargetPercent', 98.0)),

                    # Standard error budget metrics (7 columns)
                    'eb_allocated_percent': float(item.get('eBAllocatedPercent', 0.0)),
                    'eb_allocated_count': int(item.get('eBAllocatedCount', 0)),
                    'eb_consumed_percent': float(item.get('eBConsumedPercent', 0.0)),
                    'eb_consumed_count': int(item.get('eBConsumedCount', 0)),
                    'eb_actual_consumed_percent': float(item.get('eBActualConsumedPercent', 0.0)),
                    'eb_left_percent': float(item.get('eBLeftPercent', 0.0)),
                    'eb_left_count': int(item.get('eBLeftCount', 0)),

                    # Standard response budget metrics (7 columns)
                    'response_allocated_percent': float(item.get('responseAllocatedPercent', 0.0)),
                    'response_allocated_count': int(item.get('responseAllocatedCount', 0)),
                    'response_consumed_percent': float(item.get('responseConsumedPercent', 0.0)),
                    'response_consumed_count': int(item.get('responseConsumedCount', 0)),
                    'response_actual_consumed_percent': float(item.get('responseActualConsumedPercent', 0.0)),
                    'response_left_percent': float(item.get('responseLeftPercent', 0.0)),
                    'response_left_count': int(item.get('responseLeftCount', 0)),

                    # Response breach tracking (4 columns)
                    'response_breached': bool(item.get('responseBreached', False)),
                    'response_breach_count': int(item.get('responseBreachCount', 0)),
                    'response_error_rate': float(item.get('responseErrorRate', 0.0)),
                    'response_success_rate': float(item.get('responseSuccessRate', 100.0)),

                    # Aspirational SLO metrics (13 columns)
                    'aspirational_slo': float(item.get('aspirationalSLO', 99.0)),
                    'aspirational_eb_allocated_percent': float(item.get('aspirationalEBAllocatedPercent', 0.0)),
                    'aspirational_eb_allocated_count': int(item.get('aspirationalEBAllocatedCount', 0)),
                    'aspirational_eb_consumed_percent': float(item.get('aspirationalEBConsumedPercent', 0.0)),
                    'aspirational_eb_consumed_count': int(item.get('aspirationalEBConsumedCount', 0)),
                    'aspirational_eb_actual_consumed_percent': float(item.get('aspirationalEBActualConsumedPercent', 0.0)),
                    'aspirational_eb_left_percent': float(item.get('aspirationalEBLeftPercent', 0.0)),
                    'aspirational_eb_left_count': int(item.get('aspirationalEBLeftCount', 0)),
                    'aspirational_response_target_percent': float(item.get('aspirationalResponseTargetPercent', 99.0)),
                    'aspirational_response_allocated_percent': float(item.get('aspirationalResponseAllocatedPercent', 0.0)),
                    'aspirational_response_allocated_count': int(item.get('aspirationalResponseAllocatedCount', 0)),
                    'aspirational_response_consumed_percent': float(item.get('aspirationalResponseConsumedPercent', 0.0)),
                    'aspirational_response_consumed_count': int(item.get('aspirationalResponseConsumedCount', 0)) if pd.notna(item.get('aspirationalResponseConsumedCount')) else 0,
                    'aspirational_response_actual_consumed_percent': float(item.get('aspirationalResponseActualConsumedPercent', 0.0)),
                    'aspirational_response_left_percent': float(item.get('aspirationalResponseLeftPercent', 0.0)),
                    'aspirational_response_left_count': int(item.get('aspirationalResponseLeftCount', 0)),

                    # Timeliness tracking (3 columns)
                    'timeliness_consumed_percent': float(item.get('timelinessConsumedPercent', 0.0)),
                    'aspirational_timeliness_consumed_percent': float(item.get('aspirationalTimelinessConsumedPercent', 0.0)),
                    'timeliness_health': str(item.get('timelinessHealth', 'HEALTHY')),

                    # Health indicators (6 columns)
                    'eb_health': str(item.get('ebHealth', 'HEALTHY')),
                    'response_health': str(item.get('responseHealth', 'HEALTHY')),
                    'aspirational_eb_health': str(item.get('aspirationalEBHealth', 'HEALTHY')),
                    'aspirational_response_health': str(item.get('aspirationalResponseHealth', 'HEALTHY')),
                    'timeliness_severity': str(item.get('timelinessSeverity', '#07AE86')),
                    'eb_or_response_breached': bool(item.get('ebOrResponseBreached', False)),

                    # Severity color codes (4 columns)
                    'response_severity': str(item.get('responseSeverity', '#07AE86')),
                    'eb_severity': str(item.get('ebSeverity', '#07AE86')),
                    'aspirational_response_severity': str(item.get('aspirationalResponseSeverity', '#07AE86')),
                    'aspirational_eb_severity': str(item.get('aspirationalEBSeverity', '#07AE86')),

                    # Advanced metrics (3 columns)
                    'burn_rate': float(item.get('burnRate', 0.0)),
                    'eb_breached': bool(item.get('ebBreached', False)),
                    'eb_slo_status': str(item.get('eBSloStatus', 'APPROVED')),

                    # Metadata (7 columns)
                    'sort_data': float(item.get('sortData', 0.0)),
                    'data_for': str(item.get('dataFor', 'TRANSACTION')),
                    'timezone': str(item.get('timezone', 'UTC')),
                    'sre_product': str(item.get('sre_product', '')),
                    'project_id': int(item.get('projectId', 0)) if pd.notna(item.get('projectId')) else 0,
                    'project_name': str(item.get('projectName', '')),
                    'application_name': str(item.get('applicationName', '')),

                    # Data category (1 column)
                    'data_category': str(item.get('dataCategory', 'EB'))
                }

                records.append(record)

            except Exception as e:
                logger.warning(f"Skipping Platform API record {idx} due to error: {e} | Record: {item.get('transactionName', 'unknown')}")
                continue

        # Split records by dataCategory
        eb_records = [r for r in records if r.get('data_category') == 'EB']
        response_records = [r for r in records if r.get('data_category') == 'RESPONSE']

        eb_df = pd.DataFrame(eb_records).reset_index(drop=True)
        response_df = pd.DataFrame(response_records).reset_index(drop=True)

        logger.info(f"✓ Parsed {len(records)} service records from Platform API: EB={len(eb_df)}, RESPONSE={len(response_df)}")

        # Log some statistics
        if len(eb_df) > 0:
            unhealthy_count = len(eb_df[(eb_df['eb_health'] == 'UNHEALTHY') | (eb_df['response_health'] == 'UNHEALTHY')])
            high_burn_rate_count = len(eb_df[eb_df['burn_rate'] > 2.0])
            logger.info(f"  - Unhealthy services (EB): {unhealthy_count}")
            logger.info(f"  - High burn rate (>2.0) (EB): {high_burn_rate_count}")
        if len(response_df) > 0:
            logger.info(f"  - RESPONSE records loaded: {len(response_df)}")

        return eb_df, response_df

