"""Metrics aggregation and utilities."""

import pandas as pd
from typing import Dict, Any, List, Optional
from data.database.duckdb_manager import DuckDBManager
from utils.logger import setup_logger

logger = setup_logger(__name__)


class MetricsAggregator:
    """Aggregator for service metrics."""

    def __init__(self, db_manager: DuckDBManager):
        """Initialize metrics aggregator.

        Args:
            db_manager: DuckDB manager instance
        """
        self.db_manager = db_manager

    def get_top_services_by_volume(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top services by request volume.

        Args:
            limit: Number of top services to return

        Returns:
            List of top services
        """
        sql = f"""
            SELECT
                service_name,
                SUM(total_count) as total_requests,
                AVG(error_rate) as avg_error_rate,
                AVG(response_time_avg) as avg_response_time
            FROM service_logs_eb
            GROUP BY service_name
            ORDER BY total_requests DESC
            LIMIT {limit}
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            # Handle NaN values safely
            total_req = row['total_requests']
            results.append({
                'service_name': row['service_name'],
                'total_requests': int(total_req) if pd.notna(total_req) else 0,
                'avg_error_rate': row['avg_error_rate'] if pd.notna(row['avg_error_rate']) else 0.0,
                'avg_response_time': row['avg_response_time'] if pd.notna(row['avg_response_time']) else 0.0
            })

        return results

    def get_service_health_overview(self) -> Dict[str, Any]:
        """Get overall service health overview using API-provided health fields.

        Returns:
            Dictionary with health metrics broken down by eb_health and response_health.
        """
        sql = """
            SELECT
                e.service_name,
                CASE MAX(CASE e.eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as eb_health,
                CASE MAX(CASE e.aspirational_eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_eb_health,
                CASE MAX(CASE r.response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as response_health,
                CASE MAX(CASE r.aspirational_response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_response_health,
                SUM(e.total_count) as total_requests,
                SUM(e.error_count) as total_errors
            FROM service_logs_eb e
            LEFT JOIN service_logs_response r ON e.service_name = r.service_name
            GROUP BY e.service_name
        """
        df = self.db_manager.query(sql)

        total_services = len(df)
        eb_healthy = eb_at_risk = eb_unhealthy = 0
        response_healthy = response_unhealthy = 0
        total_requests = 0
        total_errors = 0

        for _, row in df.iterrows():
            eb_h = row['eb_health'] if pd.notna(row['eb_health']) else 'UNKNOWN'
            resp_h = row['response_health'] if pd.notna(row['response_health']) else 'UNKNOWN'

            if eb_h == 'HEALTHY':
                eb_healthy += 1
            elif eb_h == 'AT_RISK':
                eb_at_risk += 1
            else:
                eb_unhealthy += 1

            if resp_h == 'HEALTHY':
                response_healthy += 1
            else:
                response_unhealthy += 1

            total_requests += int(row['total_requests']) if pd.notna(row['total_requests']) else 0
            total_errors += int(row['total_errors']) if pd.notna(row['total_errors']) else 0

        overall_error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

        return {
            'total_services': total_services,
            # EB health breakdown
            'eb_healthy_services': eb_healthy,
            'eb_at_risk_services': eb_at_risk,
            'eb_unhealthy_services': eb_unhealthy,
            # Response health breakdown
            'response_healthy_services': response_healthy,
            'response_unhealthy_services': response_unhealthy,
            # Legacy keys kept for compatibility with existing UI/prompts
            'healthy_services': eb_healthy,
            'degraded_services': eb_at_risk,
            'violated_services': eb_unhealthy,
            'unhealthy_services': eb_unhealthy,
            # Totals
            'total_requests': total_requests,
            'total_errors': total_errors,
            'overall_error_rate': overall_error_rate,
            'health_percentage': (eb_healthy / total_services * 100) if total_services > 0 else 0
        }

    def get_slowest_services(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get slowest services by P99 latency (or average if P99 unavailable).

        Args:
            limit: Number of slowest services to return

        Returns:
            List of slowest services
        """
        sql = f"""
            SELECT
                service_name,
                AVG(response_time_avg) as avg_response_time,
                AVG(response_time_p50) as avg_p50,
                AVG(response_time_p95) as avg_p95,
                AVG(response_time_p99) as avg_p99,
                MAX(response_time_max) as max_response_time,
                MAX(target_response_slo_sec) as response_slo_target,
                SUM(total_count) as total_requests
            FROM service_logs_response
            GROUP BY service_name
            ORDER BY COALESCE(avg_p99, avg_response_time) DESC
            LIMIT {limit}
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            # Handle NaN values safely
            total_req = row['total_requests']
            avg_rt = row['avg_response_time']
            avg_p99 = row['avg_p99']
            avg_p95 = row['avg_p95']
            avg_p50 = row['avg_p50']
            slo_target = row['response_slo_target']

            # Use P99 for SLO check if available, otherwise use average
            check_value = avg_p99 if pd.notna(avg_p99) else avg_rt

            results.append({
                'service_name': row['service_name'],
                'avg_response_time': avg_rt if pd.notna(avg_rt) else 0.0,
                'response_time_p50': avg_p50 if pd.notna(avg_p50) else None,
                'response_time_p95': avg_p95 if pd.notna(avg_p95) else None,
                'response_time_p99': avg_p99 if pd.notna(avg_p99) else None,
                'max_response_time': row['max_response_time'] if pd.notna(row['max_response_time']) else 0.0,
                'response_slo_target': slo_target if pd.notna(slo_target) else 1.0,
                'total_requests': int(total_req) if pd.notna(total_req) else 0,
                'slo_met': (check_value <= slo_target) if (pd.notna(check_value) and pd.notna(slo_target)) else True
            })

        return results

    def get_error_prone_services(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get services with highest error rates.

        Args:
            limit: Number of services to return

        Returns:
            List of error-prone services
        """
        sql = f"""
            SELECT
                service_name,
                AVG(error_rate) as avg_error_rate,
                SUM(error_count) as total_errors,
                SUM(total_count) as total_requests,
                MAX(target_error_slo_perc) as error_slo_target
            FROM service_logs_eb
            GROUP BY service_name
            HAVING avg_error_rate > 0
            ORDER BY avg_error_rate DESC
            LIMIT {limit}
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            # Handle NaN values safely
            total_errors = row['total_errors']
            total_requests = row['total_requests']
            avg_err_rate = row['avg_error_rate']
            slo_target = row['error_slo_target']
            results.append({
                'service_name': row['service_name'],
                'avg_error_rate': avg_err_rate if pd.notna(avg_err_rate) else 0.0,
                'total_errors': int(total_errors) if pd.notna(total_errors) else 0,
                'total_requests': int(total_requests) if pd.notna(total_requests) else 0,
                'error_slo_target': slo_target if pd.notna(slo_target) else 0.0,
                'slo_met': (avg_err_rate <= slo_target) if (pd.notna(avg_err_rate) and pd.notna(slo_target)) else True
            })

        return results

    # ==================== PLATFORM API FUNCTIONS ====================
    # The following functions leverage the extended schema with burn rate,
    # health indicators, aspirational SLO metrics, and timeliness tracking

    def get_services_by_burn_rate(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get services with highest SLO burn rates.

        High burn rate indicates rapid error budget consumption and SLO breach risk.

        Args:
            limit: Number of services to return

        Returns:
            List of services sorted by burn rate (descending)
        """
        sql = f"""
            SELECT
                service_name,
                AVG(burn_rate) as avg_burn_rate,
                AVG(eb_actual_consumed_percent) as avg_eb_consumed,
                AVG(eb_left_percent) as avg_eb_left,
                AVG(error_rate) as avg_error_rate,
                CASE MAX(CASE eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as eb_health
            FROM service_logs_eb
            GROUP BY service_name
            HAVING avg_burn_rate > 0
            ORDER BY avg_burn_rate DESC
            LIMIT {limit}
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            results.append({
                'service_name': row['service_name'],
                'avg_burn_rate': row['avg_burn_rate'] if pd.notna(row['avg_burn_rate']) else 0.0,
                'avg_eb_consumed': row['avg_eb_consumed'] if pd.notna(row['avg_eb_consumed']) else 0.0,
                'avg_eb_left': row['avg_eb_left'] if pd.notna(row['avg_eb_left']) else 0.0,
                'avg_error_rate': row['avg_error_rate'] if pd.notna(row['avg_error_rate']) else 0.0,
                'eb_health': row['eb_health'] if pd.notna(row['eb_health']) else 'UNKNOWN'
            })

        return results

    def get_aspirational_slo_gap(self) -> List[Dict[str, Any]]:
        """Identify services meeting standard SLO (98%) but failing aspirational SLO (99%).

        These are 'at risk' services - one incident away from standard SLO breach.

        Returns:
            List of services with aspirational SLO gaps
        """
        sql = """
            SELECT
                service_name,
                eb_health,
                aspirational_eb_health,
                response_health,
                aspirational_response_health,
                std_eb_consumed,
                asp_eb_consumed,
                avg_burn_rate
            FROM (
                SELECT
                    e.service_name,
                    CASE MAX(CASE e.eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as eb_health,
                    CASE MAX(CASE e.aspirational_eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_eb_health,
                    CASE MAX(CASE r.response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as response_health,
                    CASE MAX(CASE r.aspirational_response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_response_health,
                    AVG(e.eb_actual_consumed_percent) as std_eb_consumed,
                    AVG(e.aspirational_eb_actual_consumed_percent) as asp_eb_consumed,
                    AVG(e.burn_rate) as avg_burn_rate
                FROM service_logs_eb e
                LEFT JOIN service_logs_response r ON e.service_name = r.service_name
                GROUP BY e.service_name
            ) s
            WHERE (eb_health = 'HEALTHY' AND aspirational_eb_health = 'UNHEALTHY')
               OR (response_health = 'HEALTHY' AND aspirational_response_health = 'UNHEALTHY')
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            results.append({
                'service_name': row['service_name'],
                'eb_health': row['eb_health'],
                'aspirational_eb_health': row['aspirational_eb_health'],
                'response_health': row['response_health'],
                'aspirational_response_health': row['aspirational_response_health'],
                'std_eb_consumed': row['std_eb_consumed'] if pd.notna(row['std_eb_consumed']) else 0.0,
                'asp_eb_consumed': row['asp_eb_consumed'] if pd.notna(row['asp_eb_consumed']) else 0.0,
                'avg_burn_rate': row['avg_burn_rate'] if pd.notna(row['avg_burn_rate']) else 0.0
            })

        return results

    def get_timeliness_issues(self) -> List[Dict[str, Any]]:
        """Find services with timeliness/scheduling problems.

        Cross-correlates with response time to identify root cause (performance vs scheduling).

        Returns:
            List of services with timeliness issues
        """
        sql = """
            SELECT
                service_name,
                timeliness_health,
                response_health,
                AVG(timeliness_consumed_percent) as avg_timeliness_consumed,
                AVG(response_time_p95) as avg_p95,
                AVG(error_rate) as avg_error_rate
            FROM service_logs_eb
            WHERE timeliness_health = 'UNHEALTHY'
            GROUP BY service_name, timeliness_health, response_health
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            results.append({
                'service_name': row['service_name'],
                'timeliness_health': row['timeliness_health'],
                'response_health': row['response_health'],
                'avg_timeliness_consumed': row['avg_timeliness_consumed'] if pd.notna(row['avg_timeliness_consumed']) else 0.0,
                'avg_p95': row['avg_p95'] if pd.notna(row['avg_p95']) else 0.0,
                'avg_error_rate': row['avg_error_rate'] if pd.notna(row['avg_error_rate']) else 0.0
            })

        return results

    def get_breach_vs_error_analysis(self, service_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Compare response SLA breach rate vs actual error rate.

        Identifies:
        - High responseErrorRate + Low errorRate = Latency issues (slow but working)
        - Low responseErrorRate + High errorRate = Reliability issues (fast but broken)

        Args:
            service_name: Specific service name (optional). If not provided, analyzes all services.

        Returns:
            List of services with breach vs error analysis
        """
        where_clause = f"WHERE e.service_name = '{service_name}'" if service_name else ""

        sql = f"""
            SELECT
                e.service_name,
                AVG(r.response_error_rate) as avg_breach_rate,
                AVG(e.error_rate) as avg_error_rate,
                AVG(r.response_breach_count) as avg_breach_count,
                AVG(e.error_count) as avg_error_count,
                AVG(r.response_time_p95) as avg_p95,
                CASE
                    WHEN AVG(r.response_error_rate) > AVG(e.error_rate) THEN 'LATENCY_ISSUE'
                    WHEN AVG(e.error_rate) > AVG(r.response_error_rate) THEN 'RELIABILITY_ISSUE'
                    ELSE 'BALANCED'
                END as issue_type
            FROM service_logs_eb e
            LEFT JOIN service_logs_response r ON e.service_name = r.service_name
            {where_clause}
            GROUP BY e.service_name
            ORDER BY avg_breach_rate DESC
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            breach_count = row['avg_breach_count']
            error_count = row['avg_error_count']
            results.append({
                'service_name': row['service_name'],
                'avg_breach_rate': row['avg_breach_rate'] if pd.notna(row['avg_breach_rate']) else 0.0,
                'avg_error_rate': row['avg_error_rate'] if pd.notna(row['avg_error_rate']) else 0.0,
                'avg_breach_count': int(breach_count) if pd.notna(breach_count) else 0,
                'avg_error_count': int(error_count) if pd.notna(error_count) else 0,
                'avg_p95': row['avg_p95'] if pd.notna(row['avg_p95']) else 0.0,
                'issue_type': row['issue_type']
            })

        return results

    def get_budget_exhausted_services(self) -> List[Dict[str, Any]]:
        """Get services that have fully exhausted their error budget.

        Services with eb_actual_consumed_percent >= 100 or eb_left_count < 0
        are over budget and need immediate attention.

        Returns:
            List of services with exhausted budgets
        """
        sql = """
            SELECT
                service_name,
                eb_actual_consumed_percent,
                eb_left_count,
                aspirational_eb_actual_consumed_percent,
                burn_rate,
                eb_health,
                AVG(error_rate) as avg_error_rate
            FROM service_logs_eb
            WHERE eb_actual_consumed_percent >= 100 OR eb_left_count < 0
            GROUP BY service_name, eb_actual_consumed_percent, eb_left_count,
                     aspirational_eb_actual_consumed_percent, burn_rate, eb_health
            ORDER BY eb_actual_consumed_percent DESC
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            eb_left = row['eb_left_count']
            results.append({
                'service_name': row['service_name'],
                'eb_actual_consumed_percent': row['eb_actual_consumed_percent'] if pd.notna(row['eb_actual_consumed_percent']) else 0.0,
                'eb_left_count': int(eb_left) if pd.notna(eb_left) else 0,
                'aspirational_eb_actual_consumed_percent': row['aspirational_eb_actual_consumed_percent'] if pd.notna(row['aspirational_eb_actual_consumed_percent']) else 0.0,
                'burn_rate': row['burn_rate'] if pd.notna(row['burn_rate']) else 0.0,
                'eb_health': row['eb_health'] if pd.notna(row['eb_health']) else 'UNKNOWN',
                'avg_error_rate': row['avg_error_rate'] if pd.notna(row['avg_error_rate']) else 0.0
            })

        return results

    def get_composite_health_score(self) -> List[Dict[str, Any]]:
        """Calculate overall health score across all dimensions.

        Aggregates: error budget, response time, timeliness, aspirational error budget,
        and aspirational response health.

        Returns:
            List of services with composite health scores (0-100)
        """
        sql = """
            SELECT
                service_name,
                (CASE WHEN eb_health = 'HEALTHY' THEN 1 ELSE 0 END +
                 CASE WHEN response_health = 'HEALTHY' THEN 1 ELSE 0 END +
                 CASE WHEN timeliness_health = 'HEALTHY' THEN 1 ELSE 0 END +
                 CASE WHEN aspirational_eb_health = 'HEALTHY' THEN 1 ELSE 0 END +
                 CASE WHEN aspirational_response_health = 'HEALTHY' THEN 1 ELSE 0 END) as healthy_dimensions,
                eb_health,
                response_health,
                timeliness_health,
                aspirational_eb_health,
                aspirational_response_health,
                avg_burn_rate
            FROM (
                SELECT
                    e.service_name,
                    CASE MAX(CASE e.eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as eb_health,
                    CASE MAX(CASE r.response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as response_health,
                    CASE MAX(CASE e.timeliness_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as timeliness_health,
                    CASE MAX(CASE e.aspirational_eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_eb_health,
                    CASE MAX(CASE r.aspirational_response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as aspirational_response_health,
                    AVG(e.burn_rate) as avg_burn_rate
                FROM service_logs_eb e
                LEFT JOIN service_logs_response r ON e.service_name = r.service_name
                GROUP BY e.service_name
            ) s
            ORDER BY healthy_dimensions ASC, avg_burn_rate DESC
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            healthy_dims = row['healthy_dimensions']
            health_score = (healthy_dims / 5.0) * 100 if pd.notna(healthy_dims) else 0.0

            results.append({
                'service_name': row['service_name'],
                'healthy_dimensions': int(healthy_dims) if pd.notna(healthy_dims) else 0,
                'health_score': health_score,
                'eb_health': row['eb_health'],
                'response_health': row['response_health'],
                'timeliness_health': row['timeliness_health'],
                'aspirational_eb_health': row['aspirational_eb_health'],
                'aspirational_response_health': row['aspirational_response_health'],
                'avg_burn_rate': row['avg_burn_rate'] if pd.notna(row['avg_burn_rate']) else 0.0
            })

        return results

    def get_severity_heatmap(self) -> List[Dict[str, Any]]:
        """Visual representation of severity across all dimensions.

        Counts red (#FD346E) vs green (#07AE86) health indicators per service
        to identify services with multiple unhealthy dimensions.

        Returns:
            List of services with severity counts
        """
        sql = """
            SELECT
                e.service_name,
                -- Count red indicators (#FD346E)
                (CASE WHEN r.response_severity = '#FD346E' THEN 1 ELSE 0 END +
                 CASE WHEN e.eb_severity = '#FD346E' THEN 1 ELSE 0 END +
                 CASE WHEN e.timeliness_severity = '#FD346E' THEN 1 ELSE 0 END +
                 CASE WHEN r.aspirational_response_severity = '#FD346E' THEN 1 ELSE 0 END +
                 CASE WHEN e.aspirational_eb_severity = '#FD346E' THEN 1 ELSE 0 END) as red_count,
                -- Count green indicators (#07AE86)
                (CASE WHEN r.response_severity = '#07AE86' THEN 1 ELSE 0 END +
                 CASE WHEN e.eb_severity = '#07AE86' THEN 1 ELSE 0 END +
                 CASE WHEN e.timeliness_severity = '#07AE86' THEN 1 ELSE 0 END +
                 CASE WHEN r.aspirational_response_severity = '#07AE86' THEN 1 ELSE 0 END +
                 CASE WHEN e.aspirational_eb_severity = '#07AE86' THEN 1 ELSE 0 END) as green_count,
                r.response_severity,
                e.eb_severity,
                e.timeliness_severity,
                AVG(e.burn_rate) as avg_burn_rate
            FROM service_logs_eb e
            LEFT JOIN service_logs_response r ON e.service_name = r.service_name
            GROUP BY e.service_name, r.response_severity, e.eb_severity, e.timeliness_severity,
                     r.aspirational_response_severity, e.aspirational_eb_severity
            ORDER BY red_count DESC, avg_burn_rate DESC
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            red_cnt = row['red_count']
            green_cnt = row['green_count']
            results.append({
                'service_name': row['service_name'],
                'red_count': int(red_cnt) if pd.notna(red_cnt) else 0,
                'green_count': int(green_cnt) if pd.notna(green_cnt) else 0,
                'response_severity': row['response_severity'],
                'eb_severity': row['eb_severity'],
                'timeliness_severity': row['timeliness_severity'],
                'avg_burn_rate': row['avg_burn_rate'] if pd.notna(row['avg_burn_rate']) else 0.0
            })

        return results

    def get_slo_governance_status(self) -> List[Dict[str, Any]]:
        """Track services by SLO approval status.

        Identifies services with SLOs under review or not yet approved,
        helping prioritize SLO governance workflow.

        Returns:
            List of services needing SLO governance attention
        """
        sql = """
            SELECT
                service_name,
                avg_burn_rate,
                eb_health,
                response_health,
                eb_breached,
                eb_left_percent,
                CASE
                    WHEN eb_health = 'UNHEALTHY' AND avg_burn_rate > 5.0 THEN 'CRITICAL'
                    WHEN eb_health = 'UNHEALTHY' THEN 'NEEDS_REVIEW'
                    WHEN eb_health = 'AT_RISK' THEN 'AT_RISK'
                    ELSE 'HEALTHY'
                END as governance_status
            FROM (
                SELECT
                    service_name,
                    AVG(burn_rate) as avg_burn_rate,
                    CASE MAX(CASE eb_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as eb_health,
                    CASE MAX(CASE response_health WHEN 'UNHEALTHY' THEN 2 WHEN 'AT_RISK' THEN 1 ELSE 0 END)
                        WHEN 2 THEN 'UNHEALTHY' WHEN 1 THEN 'AT_RISK' ELSE 'HEALTHY' END as response_health,
                    MAX(CAST(eb_breached AS INTEGER)) > 0 as eb_breached,
                    AVG(eb_left_percent) as eb_left_percent
                FROM service_logs_eb
                GROUP BY service_name
            ) s
            WHERE eb_health IN ('UNHEALTHY', 'AT_RISK')
            ORDER BY avg_burn_rate DESC
        """

        df = self.db_manager.query(sql)

        results = []
        for _, row in df.iterrows():
            results.append({
                'service_name': row['service_name'],
                'governance_status': row['governance_status'] if pd.notna(row['governance_status']) else 'UNKNOWN',
                'avg_burn_rate': row['avg_burn_rate'] if pd.notna(row['avg_burn_rate']) else 0.0,
                'eb_health': row['eb_health'] if pd.notna(row['eb_health']) else 'UNKNOWN',
                'response_health': row['response_health'] if pd.notna(row['response_health']) else 'UNKNOWN',
                'eb_breached': bool(row['eb_breached']) if pd.notna(row['eb_breached']) else False,
                'eb_left_percent': row['eb_left_percent'] if pd.notna(row['eb_left_percent']) else 0.0
            })

        return results
