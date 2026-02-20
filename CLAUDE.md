# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**SLO Chatbot** - AI-powered Service Level Objective monitoring using Claude Sonnet 4.5 via AWS Bedrock. Analyzes daily aggregated SLO metrics from WM Platform API with 20 analytics functions.

**Stack:** Streamlit + DuckDB (OLAP) + AWS Bedrock + Platform API (Keycloak OAuth2)
**Status:** Platform API migration complete (Jan 2026), OpenSearch fully deprecated

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure: AWS Bedrock, Keycloak, Platform API

# Run
streamlit run app.py

# Tests
python test_platform_api.py      # Full Platform API suite (auth + API + 20 functions)
python test_keycloak_auth.py     # Keycloak OAuth2 only
python check_data.py             # DuckDB inspection

# Debug Streamlit cache issues
find . -type d -name "__pycache__" -exec rm -r {} + && streamlit run app.py
```

## Architecture

**Data Flow:** Platform API → Keycloak → PlatformAPIClient → DataLoader → DuckDB → Analytics → Claude → User

**Key Components:**
- `data/ingestion/keycloak_auth.py` - OAuth2 auto-refresh (4 min daemon thread)
- `data/ingestion/platform_api_client.py` - Auto-pagination (unlimited services)
- `data/ingestion/data_loader.py` - Parse API → DataFrame (90+ fields)
- `data/database/duckdb_manager.py` - OLAP DB (90 cols, 5 indexes)
- `analytics/slo_calculator.py` - Error budgets, burn rates
- `analytics/degradation_detector.py` - Week-over-week comparison
- `analytics/trend_analyzer.py` - Predictions (linear regression)
- `analytics/metrics.py` - 20 analytics functions
- `agent/claude_client.py` - Bedrock client + conversation history
- `agent/function_tools.py` - Function dispatcher (20 tools)
- `app.py` - Streamlit UI (`@st.cache_resource` for all components)

**LLM Interface:** `ClaudeClient.chat_stream()` is the primary entry point used by the UI — it's a generator that yields text chunks for real-time rendering. Internally it calls `send_message()` then loops through tool calls via `handle_tool_use()` (max 5 iterations). `ClaudeClient.chat()` is the non-streaming equivalent.

**Data Loading:** Data is NOT auto-loaded. Users click "Refresh from Platform API" in the sidebar to fetch data for a selected time range (5–60 days). Token auto-refresh runs in a background daemon thread — no manual intervention needed.

## Critical Code Patterns

### 1. NaN Handling (REQUIRED)

**ALWAYS** check `pd.notna()` before converting to int/float:

```python
# ❌ WRONG - Crashes on NaN
total_requests = int(row['total_requests'])

# ✅ CORRECT
total_requests = int(row['total_requests']) if pd.notna(row['total_requests']) else 0
```

**Apply everywhere:** `analytics/*.py`, `data/ingestion/data_loader.py`, any DataFrame processing

### 2. DuckDB INSERT Pattern (CRITICAL for IndexError)

**ALWAYS** reset index after `dropna()`:

```python
df = df.reset_index(drop=True)  # CRITICAL: After dropna() → contiguous index
self.conn.execute("DELETE FROM service_logs")
self.conn.register('temp_service_df', df)
self.conn.execute("INSERT INTO service_logs SELECT * FROM temp_service_df")
self.conn.unregister('temp_service_df')
```

**Why:** `dropna()` creates non-contiguous indices (0,1,3,5...). DuckDB needs sequential (0,1,2,3...).
**Location:** `duckdb_manager.py:226-234`

### 3. JSON Serialization for Claude

**ALWAYS** use `DateTimeEncoder` for tool results:

```python
from agent.claude_client import DateTimeEncoder
json_str = json.dumps(result, cls=DateTimeEncoder)
```

Handles: `pd.Timestamp`, `datetime`, `np.integer/floating/ndarray`, `pd.NA`

### 4. Platform API Response Parsing

**Historical bug:** Previously treated entire response as single service → only loaded 1/100+ services.

```python
# ✅ CORRECT (platform_api_client.py:186-190)
if 'summary' in data and isinstance(data['summary'], list):
    return data['summary']  # Returns all services
```

API response structure: `{"totalServiceCount": 122, "summary": [{"transactionName": "...", ...}, ...]}`

## Configuration

**Environment Variables** (`.env` or Streamlit secrets):
```bash
# AWS Bedrock
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=ap-south-1
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0

# Keycloak OAuth2
KEYCLOAK_URL, KEYCLOAK_USERNAME, KEYCLOAK_PASSWORD, KEYCLOAK_CLIENT_ID=web_app

# Platform API
PLATFORM_API_URL, PLATFORM_API_APPLICATION=WMPlatform
PLATFORM_API_PAGE_SIZE=200, PLATFORM_API_VERIFY_SSL=False
```

**SLO Thresholds** (`utils/config.py`): Standard 98%, Aspirational 99%, Burn rate >2.0 (high risk), >5.0 (critical)

**Note:** `utils/config.py` still contains deprecated OpenSearch variables kept for backwards compatibility. `requirements.txt` includes `opensearch-py==2.4.2` which is unused dead weight.

## Analytics Functions (20 Active)

**Dispatcher:** `FunctionExecutor.execute()` in `agent/function_tools.py`

**Standard Performance & Health (7):** `get_service_health_overview`, `get_degrading_services`, `get_slo_violations`, `get_slowest_services`, `get_top_services_by_volume`, `get_service_summary`, `get_current_sli`

**Platform API Advanced (8):** `get_services_by_burn_rate`, `get_aspirational_slo_gap`, `get_timeliness_issues`, `get_breach_vs_error_analysis`, `get_budget_exhausted_services`, `get_composite_health_score`, `get_severity_heatmap`, `get_slo_governance_status`

**Trend (5):** `calculate_error_budget`, `get_volume_trends`, `predict_issues_today`, `get_historical_patterns`, `get_error_prone_services`

**Deprecated (3):** ❌ `error_code_distribution`, `top_errors`, `error_details_by_code` - Platform API aggregated data only

## Database Schema

**service_logs** (90+ columns, see `duckdb_manager.py` line 33-170 for full schema):
- **Core:** `service_name`, `record_time`, `total_count`, `error_count/rate`, `success_count/rate`
- **Response times:** `response_time_p50/p95/p99` (8 percentiles available)
- **Standard SLO:** `eb_allocated/consumed/left_percent`, `eb_health`, `eb_breached`
- **Aspirational:** `aspirational_slo`, `aspirational_eb_health`, `aspirational_response_health`
- **Advanced:** `burn_rate`, `timeliness_health`, `eb_severity`, `response_severity`, `eb_slo_status`
- **Indexes:** `service_time`, `service_name`, `burn_rate`, `eb_health`, `response_health`

## Adding New Analytics Functions

1. Implement method in `analytics/metrics.py` or appropriate module
2. Add wrapper to `FunctionExecutor.function_map` in `agent/function_tools.py`
3. Add tool definition to `TOOLS` list in `agent/function_tools.py` (JSON schema)
4. Add to system prompt in `app.py` `display_chat()` (lines 135-329)
5. Test with `python test_platform_api.py`

**Code safety checklist:**
- Add NaN checks: `int(val) if pd.notna(val) else 0`
- Use `DateTimeEncoder` for JSON serialization
- Reset DataFrame index before DuckDB operations

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

## Streamlit Cloud Deployment

**Python Version:** 3.12 (`.python-version` file)

**Common Issues:**
- URL typo: `wmerrorbudgetstatisticsservice` (not "statstics")
- Hostname: `wm-sandbox-1.watermelon.us` (with hyphens)
- TOML format: URLs on single line, no leading spaces
