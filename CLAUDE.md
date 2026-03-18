# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**SLO Chatbot** - AI-powered Service Level Objective monitoring using Claude Sonnet 4.5 via AWS Bedrock (cross-region inference, `global.` prefix). Analyzes daily aggregated SLO metrics from WM Platform API with 20 analytics functions.

**Stack:** Streamlit + DuckDB (OLAP) + AWS Bedrock + Platform API (Keycloak OAuth2)

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure: AWS Bedrock, Keycloak, Platform API

# Run
streamlit run app.py
# or
./run.sh  # Wrapper that activates venv + starts Streamlit

# Tests
python test_platform_api.py      # Full Platform API suite (auth + API + 20 functions)
python test_keycloak_auth.py     # Keycloak OAuth2 only

# Debug Streamlit cache issues
find . -type d -name "__pycache__" -exec rm -r {} + && streamlit run app.py
```

## Architecture

**Data Flow:** Platform API → Keycloak → PlatformAPIClient → DataLoader → DuckDB (2 tables) → Analytics → Claude → User

**Key Components:**
- `data/ingestion/keycloak_auth.py` - OAuth2 auto-refresh (4 min daemon thread)
- `data/ingestion/platform_api_client.py` - Auto-pagination (unlimited services)
- `data/ingestion/data_loader.py` - Parse API → split into EB and RESPONSE DataFrames
- `data/database/duckdb_manager.py` - OLAP DB (2 tables, 90+ cols each)
- `analytics/slo_calculator.py` - Error budgets, burn rates
- `analytics/degradation_detector.py` - Week-over-week comparison
- `analytics/trend_analyzer.py` - Predictions (linear regression)
- `analytics/metrics.py` - 20 analytics functions
- `agent/claude_client.py` - Bedrock client + conversation history
- `agent/function_tools.py` - Function dispatcher (20 tools)
- `app.py` - Streamlit UI (`@st.cache_resource` for all components)

**LLM Interface:** `ClaudeClient.chat_stream()` is the primary entry point — yields text chunks for real-time rendering. Internally calls `send_message()` then loops through tool calls via `handle_tool_use()` (max 5 iterations). The system prompt in `app.py` `display_chat()` restricts the chatbot to SLO-related questions only — it explicitly declines off-topic queries.

**Data Loading:** Data is NOT auto-loaded. Users click "Refresh from Platform API" in the sidebar to fetch data for a selected time range (5–60 days). Token auto-refresh runs in a background daemon thread.

**Streamlit Cache:** All components use `@st.cache_resource` (singletons per session). After code changes, clear cache with the pycache command above and restart — browser refresh alone is insufficient.

## Critical Code Patterns

### 1. NaN Handling (REQUIRED)

**ALWAYS** check `pd.notna()` before converting to int/float:

```python
# ❌ WRONG - Crashes on NaN
total_requests = int(row['total_requests'])

# ✅ CORRECT
total_requests = int(row['total_requests']) if pd.notna(row['total_requests']) else 0
```

### 2. DuckDB INSERT Pattern (CRITICAL for IndexError)

**ALWAYS** use named-column insert and reset index after `dropna()`:

```python
df = df.reset_index(drop=True)  # CRITICAL: contiguous index required
self.conn.execute("DELETE FROM service_logs_eb")
self.conn.register('temp_df', df)
cols = ', '.join(df.columns.tolist())
self.conn.execute(f"INSERT INTO service_logs_eb ({cols}) SELECT {cols} FROM temp_df")
self.conn.unregister('temp_df')
```

**Why named cols:** Positional `SELECT *` causes type mismatches (e.g. color strings into BOOLEAN columns).
**Why reset_index:** `dropna()` creates non-contiguous indices. DuckDB needs sequential (0,1,2,3...).

### 3. JSON Serialization for Claude

**ALWAYS** use `DateTimeEncoder` for tool results:

```python
from agent.claude_client import DateTimeEncoder
json_str = json.dumps(result, cls=DateTimeEncoder)
```

Handles: `pd.Timestamp`, `datetime`, `np.integer/floating/ndarray`, `pd.NA`

### 4. Platform API Response Format

API returns a **flat list** (no wrapper). Each service produces **2 records**: one with `dataCategory=EB` and one with `dataCategory=RESPONSE`.

```python
# data_loader splits on dataCategory:
eb_records = [r for r in records if r.get('data_category') == 'EB']
response_records = [r for r in records if r.get('data_category') == 'RESPONSE']
```

## Configuration

**Environment Variables** (`.env` or Streamlit secrets):
```bash
# AWS Bedrock
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=ap-south-1
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0

# Keycloak OAuth2
KEYCLOAK_URL, KEYCLOAK_USERNAME, KEYCLOAK_PASSWORD, KEYCLOAK_CLIENT_ID=web_app

# Platform API
PLATFORM_API_URL=https://wm-sandbox-1.watermelon.us/services/wmerrorbudgetstatisticsservice/api/transactions/distinct/top-5/ALL
PLATFORM_API_APPLICATION=WMPlatform
PLATFORM_API_APPLICATION_ID=31854
PLATFORM_API_PROJECT_ID=215853
PLATFORM_API_PAGE_SIZE=200, PLATFORM_API_VERIFY_SSL=False

# Optional overrides
DEFAULT_TIME_WINDOW_DAYS=5, MAX_TIME_WINDOW_DAYS=60
LOG_LEVEL=INFO
```

**SLO Thresholds** (`utils/config.py`): Standard 98%, Response time 1.0s, Degradation trigger 20% change
**Burn rate severity** (`analytics/slo_calculator.py`): `<1` (healthy), `<2` (warning), `<10` (critical), `>=10` (emergency)

## Database Schema

**Two tables** in `duckdb_manager.py`:

**`service_logs_eb`** (EB category — error budget records):
- **Core:** `service_name`, `record_time`, `total_count`, `error_count/rate`, `success_count/rate`
- **Standard SLO:** `eb_allocated/consumed/left_percent`, `eb_health`, `eb_breached`, `burn_rate`
- **Aspirational:** `aspirational_slo`, `aspirational_eb_health`, `aspirational_eb_left_percent`
- **Timeliness:** `timeliness_health`, `timeliness_consumed_percent`
- **Severity:** `eb_severity`, `aspirational_eb_severity`, `timeliness_severity`
- **Indexes:** `service_time`, `service_name`, `burn_rate`, `eb_health`, `eb_breached`

**`service_logs_response`** (RESPONSE category — response time records):
- Same schema as `service_logs_eb` but primary data is response time percentiles
- **Response times:** `response_time_p25/p50/p75/p80/p85/p90/p95/p99`, `response_time_avg`
- **Response budget:** `response_allocated/consumed/left_percent`, `response_health`, `response_breached`
- **Indexes:** `resp_service_time`, `resp_service_name`

**Query routing in analytics:**
- EB metrics (burn rate, error budget) → query `service_logs_eb`
- Response times, slowest services → query `service_logs_response`
- Combined (health overview, composite score) → `LEFT JOIN service_logs_eb e ON e.service_name = r.service_name`

## Analytics Functions (20 Active)

**Dispatcher:** `FunctionExecutor.execute()` in `agent/function_tools.py`

**Standard Performance & Health (7):** `get_service_health_overview`, `get_degrading_services`, `get_slo_violations`, `get_slowest_services`, `get_top_services_by_volume`, `get_service_summary`, `get_current_sli`

**Platform API Advanced (8):** `get_services_by_burn_rate`, `get_aspirational_slo_gap`, `get_timeliness_issues`, `get_breach_vs_error_analysis`, `get_budget_exhausted_services`, `get_composite_health_score`, `get_severity_heatmap`, `get_slo_governance_status`

**Trend (5):** `calculate_error_budget`, `get_volume_trends`, `predict_issues_today`, `get_historical_patterns`, `get_error_prone_services`

## Adding New Analytics Functions

1. Implement method in `analytics/metrics.py` or appropriate module
2. Add wrapper to `FunctionExecutor.function_map` in `agent/function_tools.py`
3. Add tool definition to `TOOLS` list in `agent/function_tools.py` (JSON schema)
4. Add to system prompt in `app.py` `display_chat()`
5. Test with `python test_platform_api.py`

**Code safety checklist:**
- Add NaN checks: `int(val) if pd.notna(val) else 0`
- Use `DateTimeEncoder` for JSON serialization
- Reset DataFrame index before DuckDB operations
- Use named-column INSERT (not `SELECT *`)

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Streamlit not picking up changes | `find . -type d -name "__pycache__" -exec rm -r {} + && streamlit run app.py` |
| `IndexError: index N out of bounds` | `df.reset_index(drop=True)` before DuckDB insert |
| NaN conversion crash | Use `int(val) if pd.notna(val) else 0` pattern |
| `Timestamp not JSON serializable` | `json.dumps(result, cls=DateTimeEncoder)` |
| 401 Unauthorized | Update `.env`, test with `python test_keycloak_auth.py` |
| Missing columns error | Delete `data/database/slo_analytics.duckdb`, restart app |
| No data in chat responses | User must click "Refresh from Platform API" in sidebar first |
| DuckDB lock error when reading | Copy `.duckdb` + `.duckdb.wal` files together to `/tmp/` first |

## Streamlit Cloud Deployment

**Python Version:** 3.12 (`.python-version` file)

**Secrets format** (`secrets.toml`): URLs must be on a single line with no leading spaces. Use `[section]` headers matching env var groups above.
