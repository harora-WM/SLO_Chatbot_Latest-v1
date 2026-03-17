"""Degradation detector for identifying services with declining performance."""

import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from data.database.duckdb_manager import DuckDBManager
from utils.logger import setup_logger
from utils.config import DEGRADATION_WINDOW_MINUTES, DEGRADATION_THRESHOLD_PERCENT

logger = setup_logger(__name__)


class DegradationDetector:
    """Detector for service performance degradation."""

    def __init__(self, db_manager: DuckDBManager):
        """Initialize degradation detector.

        Args:
            db_manager: DuckDB manager instance
        """
        self.db_manager = db_manager

    def detect_degrading_services(self,
                                  time_window_minutes: int = DEGRADATION_WINDOW_MINUTES,
                                  threshold_percent: float = DEGRADATION_THRESHOLD_PERCENT) -> List[Dict[str, Any]]:
        """Detect services that are degrading over a time window.

        Degradation is detected by comparing recent metrics vs baseline.

        Args:
            time_window_minutes: Time window for analysis (default: 30 minutes)
            threshold_percent: Threshold for degradation (default: 20%)

        Returns:
            List of degrading services with details
        """
        # Get time range from database
        time_range = self.db_manager.get_time_range()
        if not time_range['max_time']:
            logger.warning("No data available in database")
            return []

        # Define time windows
        current_time = time_range['max_time']
        window_start = current_time - timedelta(minutes=time_window_minutes)
        baseline_end = window_start
        baseline_start = baseline_end - timedelta(minutes=time_window_minutes)

        # Get metrics for recent window
        recent_sql = f"""
            SELECT
                service_name,
                AVG(error_rate) as avg_error_rate,
                AVG(response_time_avg) as avg_response_time,
                AVG(response_time_p95) as avg_response_time_p95,
                AVG(response_time_p99) as avg_response_time_p99,
                SUM(total_count) as total_requests,
                SUM(error_count) as total_errors
            FROM service_logs_eb
            WHERE record_time >= '{window_start}' AND record_time <= '{current_time}'
            GROUP BY service_name
        """
        recent_df = self.db_manager.query(recent_sql)

        # Get metrics for baseline window
        baseline_sql = f"""
            SELECT
                service_name,
                AVG(error_rate) as avg_error_rate,
                AVG(response_time_avg) as avg_response_time,
                AVG(response_time_p95) as avg_response_time_p95,
                AVG(response_time_p99) as avg_response_time_p99,
                SUM(total_count) as total_requests,
                SUM(error_count) as total_errors
            FROM service_logs_eb
            WHERE record_time >= '{baseline_start}' AND record_time < '{baseline_end}'
            GROUP BY service_name
        """
        baseline_df = self.db_manager.query(baseline_sql)

        # Merge and compare
        comparison = recent_df.merge(
            baseline_df,
            on='service_name',
            suffixes=('_recent', '_baseline'),
            how='inner'
        )

        degrading_services = []

        for _, row in comparison.iterrows():
            # Calculate percentage changes
            error_rate_change = self._calculate_percent_change(
                row['avg_error_rate_baseline'],
                row['avg_error_rate_recent']
            )

            response_time_change = self._calculate_percent_change(
                row['avg_response_time_baseline'],
                row['avg_response_time_recent']
            )

            # Calculate P95/P99 changes (if available)
            p95_change = self._calculate_percent_change(
                row['avg_response_time_p95_baseline'],
                row['avg_response_time_p95_recent']
            ) if pd.notna(row['avg_response_time_p95_recent']) and pd.notna(row['avg_response_time_p95_baseline']) else 0.0

            p99_change = self._calculate_percent_change(
                row['avg_response_time_p99_baseline'],
                row['avg_response_time_p99_recent']
            ) if pd.notna(row['avg_response_time_p99_recent']) and pd.notna(row['avg_response_time_p99_baseline']) else 0.0

            # Check if degrading (include P95/P99 in degradation check)
            is_degrading = (
                error_rate_change > threshold_percent or
                response_time_change > threshold_percent or
                p95_change > threshold_percent or
                p99_change > threshold_percent
            )

            if is_degrading:
                # Handle NaN values safely
                total_req = row['total_requests_recent']
                total_err = row['total_errors_recent']
                degrading_services.append({
                    'service_name': row['service_name'],
                    'error_rate_recent': row['avg_error_rate_recent'],
                    'error_rate_baseline': row['avg_error_rate_baseline'],
                    'error_rate_change_percent': error_rate_change,
                    'response_time_recent': row['avg_response_time_recent'],
                    'response_time_baseline': row['avg_response_time_baseline'],
                    'response_time_change_percent': response_time_change,
                    'response_time_p95_recent': row['avg_response_time_p95_recent'] if pd.notna(row['avg_response_time_p95_recent']) else None,
                    'response_time_p95_baseline': row['avg_response_time_p95_baseline'] if pd.notna(row['avg_response_time_p95_baseline']) else None,
                    'response_time_p95_change_percent': p95_change,
                    'response_time_p99_recent': row['avg_response_time_p99_recent'] if pd.notna(row['avg_response_time_p99_recent']) else None,
                    'response_time_p99_baseline': row['avg_response_time_p99_baseline'] if pd.notna(row['avg_response_time_p99_baseline']) else None,
                    'response_time_p99_change_percent': p99_change,
                    'total_requests_recent': int(total_req) if pd.notna(total_req) else 0,
                    'total_errors_recent': int(total_err) if pd.notna(total_err) else 0,
                    'severity': self._classify_severity(error_rate_change, response_time_change, p95_change, p99_change)
                })

        # Sort by severity (highest change first, prioritizing P99)
        degrading_services.sort(
            key=lambda x: max(
                x['error_rate_change_percent'],
                x['response_time_change_percent'],
                x.get('response_time_p95_change_percent', 0),
                x.get('response_time_p99_change_percent', 0)
            ),
            reverse=True
        )

        logger.info(f"Found {len(degrading_services)} degrading services")
        return degrading_services

    def get_volume_trends(self,
                         service_name: str,
                         time_window_minutes: int = 30) -> Dict[str, Any]:
        """Get volume trends for a service.

        Args:
            service_name: Service name
            time_window_minutes: Time window for analysis

        Returns:
            Dictionary with volume trend data
        """
        # Get time range
        time_range = self.db_manager.get_time_range()
        if not time_range['max_time']:
            return {'error': 'No data available'}

        current_time = time_range['max_time']
        window_start = current_time - timedelta(minutes=time_window_minutes)

        sql = f"""
            SELECT
                record_time,
                total_count,
                error_count,
                success_count,
                error_rate,
                response_time_avg
            FROM service_logs_eb
            WHERE service_name = '{service_name}'
                AND record_time >= '{window_start}'
                AND record_time <= '{current_time}'
            ORDER BY record_time ASC
        """

        df = self.db_manager.query(sql)

        if df.empty:
            return {'error': f'No data found for service {service_name}'}

        # Calculate trends
        total_volume = df['total_count'].sum()
        total_errors = df['error_count'].sum()
        avg_error_rate = df['error_rate'].mean()
        avg_response_time = df['response_time_avg'].mean()

        # Time series data
        time_series = []
        for _, row in df.iterrows():
            # Handle NaN values safely
            total_cnt = row['total_count']
            err_cnt = row['error_count']
            time_series.append({
                'timestamp': str(row['record_time']),
                'total_requests': int(total_cnt) if pd.notna(total_cnt) else 0,
                'errors': int(err_cnt) if pd.notna(err_cnt) else 0,
                'error_rate': row['error_rate'] if pd.notna(row['error_rate']) else 0.0,
                'response_time': row['response_time_avg'] if pd.notna(row['response_time_avg']) else 0.0
            })

        return {
            'service_name': service_name,
            'time_window_minutes': time_window_minutes,
            'summary': {
                'total_volume': int(total_volume) if pd.notna(total_volume) else 0,
                'total_errors': int(total_errors) if pd.notna(total_errors) else 0,
                'avg_error_rate': avg_error_rate if pd.notna(avg_error_rate) else 0.0,
                'avg_response_time': avg_response_time if pd.notna(avg_response_time) else 0.0
            },
            'time_series': time_series
        }

    @staticmethod
    def _calculate_percent_change(baseline: float, current: float) -> float:
        """Calculate percentage change from baseline to current.

        Args:
            baseline: Baseline value
            current: Current value

        Returns:
            Percentage change
        """
        if baseline == 0:
            return 100.0 if current > 0 else 0.0
        return ((current - baseline) / baseline) * 100

    @staticmethod
    def _classify_severity(error_rate_change: float, response_time_change: float,
                          p95_change: float = 0.0, p99_change: float = 0.0) -> str:
        """Classify degradation severity.

        Args:
            error_rate_change: Error rate change percentage
            response_time_change: Response time change percentage
            p95_change: P95 latency change percentage
            p99_change: P99 latency change percentage

        Returns:
            Severity level: critical, warning, or minor
        """
        max_change = max(error_rate_change, response_time_change, p95_change, p99_change)

        if max_change > 100:
            return 'critical'
        elif max_change > 50:
            return 'warning'
        else:
            return 'minor'
