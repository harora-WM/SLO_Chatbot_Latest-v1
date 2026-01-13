# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**SLO Chatbot** - AI-powered Service Level Objective monitoring using Claude Sonnet 4.5 via AWS Bedrock. Analyzes **daily aggregated SLO metrics from the WM Platform Error Budget Statistics Service API** with **20 analytics functions**.

**Latest Update (January 2026):** Migrated from OpenSearch to Platform API (90+ metrics, unlimited pagination, 5-60 day windows).

## Additional Documentation

- **PLATFORM_API_MIGRATION.md** - Complete migration guide (600+ lines)
- **README.md** - Main project documentation
- **DEPRECATED.md** - Deprecated files and migration paths

## Quick Start

```bash
# First-time setup
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Then edit .env with your Keycloak credentials

# Run the application
streamlit run app.py

# Run Platform API tests (requires valid Keycloak credentials in .env)
python test_platform_api.py

# Test Keycloak authentication separately
python test_keycloak_auth.py

# Inspect database contents
python check_data.py

# Legacy test suite (uses local JSON files, not Platform API)
python test_system.py
```

## Architecture

### Data Flow
```
Platform API → Keycloak OAuth2 → PlatformAPIClient (Pagination) → DataLoader → DuckDB (90+ cols) → Analytics → Claude → User
```

### Key Architectural Decisions
1. **DuckDB (OLAP)** - SLO data is structured time-series. No vector DB needed - SQL aggregations are faster and more precise.
2. **Daily aggregation** - Better for long-term trends (5-60 days) vs hourly (4-hour windows)
3. **Keycloak OAuth2** - Background token refresh every 4 minutes (daemon thread)
4. **Automatic pagination** - No 10k limit, unlimited services

### Component Layers

**Data:** `data/ingestion/` + `data/database/`
- `keycloak_auth.py` - OAuth2 with auto-refresh (4 min)
- `platform_api_client.py` - Pagination (unlimited services)
- `data_loader.py` - Parse Platform API → DataFrames (90+ fields)
- `duckdb_manager.py` - OLAP DB (90+ columns, indexed)

**Analytics:** `analytics/`
- `slo_calculator.py` - SLI/SLO metrics, error budgets, burn rates
- `degradation_detector.py` - Week-over-week comparison
- `trend_analyzer.py` - Predictions (linear regression, 2+ weeks data)
- `metrics.py` - 20 functions (8 new Platform API functions)

**Agent:** `agent/`
- `claude_client.py` - AWS Bedrock + conversation history
- `function_tools.py` - FunctionExecutor dispatches 20 tool calls

**UI:** `app.py` - Streamlit with `@st.cache_resource` for component initialization

## Critical Code Patterns

### NaN Handling Pattern

**ALWAYS** use `pd.notna()` checks before converting to integers. This is critical throughout the codebase:

```python
# ❌ WRONG - Will crash on NaN
total_requests = int(row['total_requests'])

# ✅ CORRECT - Handles NaN safely
total_req = row['total_requests']
total_requests = int(total_req) if pd.notna(total_req) else 0
```

This pattern appears in:
- `analytics/degradation_detector.py`
- `analytics/trend_analyzer.py`
- `analytics/slo_calculator.py`
- `analytics/metrics.py`
- `data/ingestion/data_loader.py`

### Platform API Response Parsing Pattern

**CRITICAL:** The Platform API returns services nested in a `summary` array. Always extract from this array:

```python
# ❌ WRONG - Treats entire response as 1 service
if isinstance(data, dict):
    return [data]

# ✅ CORRECT - Extracts services from summary array
if isinstance(data, dict):
    if 'summary' in data and isinstance(data['summary'], list):
        return data['summary']  # Returns 100+ services
    return [data]  # Fallback for other formats
```

**Platform API Response Structure:**
```json
{
  "totalServiceCount": 122,
  "totalSLO": 244,
  "summary": [
    { "transactionName": "service1", "errorRate": 0.5, ... },
    { "transactionName": "service2", "errorRate": 1.2, ... },
    // ... 100+ more services
  ]
}
```

**This bug caused only 1 service to load instead of 100+**. Fixed in `platform_api_client.py:186-190`.

### Platform API Data Loading Pattern

**Always use the complete 90+ field mapping** when loading Platform API data:

```python
# In data_loader.py - load_service_logs_from_platform_api()
from data.ingestion.platform_api_client import PlatformAPIClient
from data.ingestion.keycloak_auth import KeycloakAuthManager

# Initialize clients
auth_manager = KeycloakAuthManager()  # Auto-refreshing token
api_client = PlatformAPIClient(auth_manager)

# Fetch data (automatic pagination)
end_time = int(datetime.now().timestamp() * 1000)
start_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
response = api_client.query_service_health(start_time, end_time)

# Load into DataFrame with 90+ field mapping
df = data_loader.load_service_logs_from_platform_api(response)

# Insert into DuckDB
db_manager.insert_service_logs(df)
```

**Key Platform API fields**:
- Core: `service_name`, `total_count`, `error_rate`, `success_rate`
- Percentiles: `response_time_p25/p50/p75/p80/p85/p90/p95/p99`
- Error budgets: `eb_allocated_percent`, `eb_consumed_percent`, `eb_actual_consumed_percent`, `eb_left_percent`, `eb_health`
- Aspirational SLO: `aspirational_slo`, `aspirational_eb_health`, `aspirational_response_health`
- Advanced: `burn_rate`, `timeliness_health`, `eb_severity`, `response_severity`, `eb_slo_status`

### JSON Serialization Pattern for Claude Tool Results

**ALWAYS** use the custom `DateTimeEncoder` when serializing tool results to send to Claude:

```python
import json
from agent.claude_client import DateTimeEncoder

# ✅ CORRECT - Handles pandas Timestamp, datetime, numpy types
result = {"timestamp": pd.Timestamp.now(), "value": np.int64(42)}
json_str = json.dumps(result, cls=DateTimeEncoder)

# ❌ WRONG - Will crash with "Object of type Timestamp is not JSON serializable"
json_str = json.dumps(result)
```

**What the DateTimeEncoder handles**:
- `pd.Timestamp` → ISO format string
- `datetime/date` → ISO format string
- `np.integer` → Python int
- `np.floating` → Python float
- `np.ndarray` → Python list
- `pd.NA/np.nan` → `null`

This is critical in `agent/claude_client.py` where tool results are serialized to send back to Claude.

### Tool Calling Response Handling

When Claude uses tools, the response contains `content` blocks with type `tool_use`. Handle them like this:

```python
response_content = response_body.get("content", [])

for content in response_content:
    if content.get("type") == "tool_use":
        tool_name = content.get("name")
        tool_input = content.get("input", {})
        tool_use_id = content.get("id")

        # Execute function
        result = function_executor.execute(tool_name, tool_input)

        # Send result back in tool_result format
        tool_result = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(result, cls=DateTimeEncoder)
        }
```

The `tool_use_id` from Claude's response must be included in the `tool_result` sent back. This is how Claude matches results to requests in multi-tool scenarios.

### DuckDB INSERT Pattern

**ALWAYS** use this pattern when inserting DataFrames into DuckDB:

```python
# ✅ CORRECT approach
df = df.reset_index(drop=True)  # Reset index after any dropna() operations
self.conn.execute("DELETE FROM service_logs")

# Register DataFrame explicitly to avoid caching issues
self.conn.register('temp_service_df', df)
self.conn.execute("INSERT INTO service_logs SELECT * FROM temp_service_df")
self.conn.unregister('temp_service_df')
```

**Why this is critical**:
1. After using `dropna()` or filtering, pandas DataFrames have non-contiguous indices (e.g., 0, 1, 3, 5, ...)
2. DuckDB expects continuous indices (0, 1, 2, 3, ...)
3. Using `register()` explicitly registers the DataFrame with DuckDB, avoiding stale references
4. Without this, large datasets (>1000 rows) may throw `IndexError: index N is out of bounds`

**DO NOT** use `INSERT OR REPLACE` with multiple constraints. Use `DELETE + INSERT` instead.

This pattern is in `data/database/duckdb_manager.py` (lines 228-234 for service logs).

## Configuration

**File:** `utils/config.py` - Centralized configuration with Streamlit Cloud support (secrets → env vars fallback)

**Key Thresholds:**
- SLO: 98% standard, 99% aspirational | Error rate: 1% | Response time: 1s
- Burn rate: >2.0 high risk, >5.0 critical
- Time windows: 5 days default, 60 days max | Degradation: 7-day windows

**Credentials:** `.env` file (use `.env.example` as template):
- AWS Bedrock: Access key, secret, region (`ap-south-1`), model ID (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- Keycloak: URL, username, password, client_id (`web_app`)
- Platform API: URL, application (`WMPlatform`), page size (200), verify_ssl (False for sandbox)

**Streamlit Cloud:** Use secrets instead of `.env` (Settings > Secrets). Config automatically checks secrets first.

## Tool Calling Flow

**System Prompt:** `app.py` `display_chat()` function (lines ~135-329)

**Flow:** User → Streamlit → Claude + TOOLS → tool_use blocks → FunctionExecutor → Analytics → DateTimeEncoder → Claude → User

**FunctionExecutor** (`agent/function_tools.py`): Dispatcher with `function_map` routing 20 functions to analytics modules.

### Available Functions (20 usable)

**Standard (7):** health_overview, degrading_services, slo_violations, slowest_services, top_services_by_volume, service_summary, current_sli

**Platform API Advanced (8):** services_by_burn_rate, aspirational_slo_gap, timeliness_issues, breach_vs_error_analysis, budget_exhausted_services, composite_health_score, severity_heatmap, slo_governance_status

**Performance (5):** calculate_error_budget, volume_trends, predict_issues_today, historical_patterns, error_prone_services

**Deprecated (3):** ❌ error_code_distribution, top_errors, error_details_by_code (no error_logs table)

## Time-Series Analysis

**Degradation Detection** (`analytics/degradation_detector.py`): Compare 7-day windows (baseline vs recent). Flag if >20% change in error_rate, burn_rate, or response_time.

**Note:** Use day-based windows (7, 30 days), not minute-based.

## Platform API Integration

**KeycloakAuthManager** (`keycloak_auth.py`): Auto-refresh token every 4 min in daemon thread. No user intervention.

**PlatformAPIClient** (`platform_api_client.py`): Automatic pagination (no 10k limit). Loops through pages until empty.

**Data Loading Workflow** (on "🔄 Refresh"):
1. Calculate time window (5-60 days)
2. Fetch: `api_client.query_service_health()` (auto-pagination)
3. Parse: `data_loader.load_service_logs_from_platform_api()` (90+ fields → DataFrame)
4. Reset index: `df.reset_index(drop=True)`
5. Clear & insert: `DELETE + INSERT` (never `INSERT OR REPLACE`)
6. Update state: `st.session_state.data_loaded = True`

**Performance:** 5-15 sec for 100+ services, 7+ days.

## Testing

**Platform API Tests:** `python test_platform_api.py` (requires valid Keycloak creds in `.env`)
- Tests: Auth, pagination, data loading, 20 functions, end-to-end
- Expected: 5/5 passing

**Legacy Tests:** `python test_system.py` (local JSON files, not Platform API)

**Auth Test:** `python test_keycloak_auth.py` (standalone OAuth2 test)

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| **Streamlit not picking up changes** | `@st.cache_resource` caches components | Stop → clear `__pycache__` → restart |
| **IndexError: index N out of bounds** | Non-contiguous DataFrame index after `dropna()` | `df.reset_index(drop=True)` before DuckDB insert |
| **NaN to integer conversion** | Missing `pd.notna()` checks | Use pattern: `int(val) if pd.notna(val) else 0` |
| **DuckDB constraint errors** | Multiple constraints with `INSERT OR REPLACE` | Use `DELETE + INSERT` pattern |
| **Timestamp not JSON serializable** | pandas/numpy types in tool results | Use `json.dumps(result, cls=DateTimeEncoder)` |
| **Invalid user credentials** | Wrong Keycloak creds | Update `.env` KEYCLOAK_USERNAME/PASSWORD |
| **401 Unauthorized** | Auth failed | Run `python test_keycloak_auth.py` |
| **No data loaded** | Wrong Platform API URL | Verify PLATFORM_API_URL/APPLICATION in `.env` |
| **SSL verification errors** | Sandbox cert issues | Set `PLATFORM_API_VERIFY_SSL=False` (sandbox only) |
| **Missing columns** | Old DB schema | Delete `slo_analytics.duckdb`, restart |
| **Only 1 service loads** | Wrong parsing (not extracting `summary[]` array) | Check `platform_api_client.py:186-190` |
| **Only 1 day of data** | Daily index may not retain history | Check with Platform API team on retention policy |

## Database Schema

**service_logs** (90+ columns, `duckdb_manager.py`):
- PK: `id` | Identifiers: `app_id`, `sid`, `service_name` | Time: `record_time`
- Core: `total_count`, `error_count/rate`, `success_count/rate`, `response_time_*` (p25-p99)
- Error budgets: `eb_*` (allocated, consumed, left, health, breached)
- Aspirational: `aspirational_*` (slo, eb_health, response_health)
- Advanced: `burn_rate`, `timeliness_health`, `eb_severity`, `response_severity`, `eb_slo_status`

**Indexes:** service_time, service_name, burn_rate, eb_health, response_health, eb_breached

**error_logs:** ⚠️ DEPRECATED (backward compat only)

## File Organization

```
analytics/          slo_calculator, degradation_detector, trend_analyzer, metrics
agent/              claude_client (Bedrock), function_tools (dispatcher)
data/ingestion/     keycloak_auth, platform_api_client, data_loader
data/database/      duckdb_manager
utils/              config, logger
app.py              Streamlit UI
test_*.py           Test suites
```

## Streamlit App

**Tabs:** Dashboard (metrics/charts) | Chat (Claude interface)

**Initialization** (`@st.cache_resource`): Components init once per session. Code changes require restart + cache clear.

**State:**
- `st.session_state.messages` - Chat history
- `st.session_state.data_loaded` - Data fetch status

**Conversation History** (`claude_client.py`):
- Maintained as instance variable
- Tool results sent as `{"role": "user", "content": [tool_result_blocks]}`
- Each `tool_result` must include `tool_use_id` from Claude's `tool_use`
- History passed to Bedrock on every request

## Development Workflows

### Modifying Analytics Functions
1. Add NaN checks: `int(val) if pd.notna(val) else 0`
2. Test: `python test_platform_api.py`
3. Return consistent structures (dict/list)
4. Use `DateTimeEncoder` for serialization

### Adding New Analytics Functions
1. Add method to analytics module (e.g., `metrics.py`)
2. Add wrapper in `FunctionExecutor` (`function_tools.py`)
3. Register in `function_map` in `execute()`
4. Add tool definition to `TOOLS` list
5. Update system prompt (`app.py` display_chat)
6. Test via Streamlit

### Debugging Streamlit Cache
```bash
# Stop → clear cache → restart
find . -type d -name "__pycache__" -exec rm -r {} +
streamlit run app.py
```

## Platform API Migration (Jan 2026)

**Status:** ✅ Complete | **Breaking:** None (backward compatible)

**Changes:** OpenSearch→Platform API | Basic Auth→Keycloak OAuth2 | 10k→Unlimited | 4hrs→5-60 days | Hourly→Daily | 26→90+ cols | 15→20 functions

**New:** Burn rate monitoring, multi-tier SLO (98%/99%), aspirational gap detection, timeliness tracking, composite health (0-100), breach vs error analysis, severity heatmap

**See:** PLATFORM_API_MIGRATION.md | DEPRECATED.md
