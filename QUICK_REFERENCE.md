# SLO Chatbot - Quick Reference Guide

## What You Need to Know (5 Minutes)

### 1. What is it?
AI-powered SLO (Service Level Objective) monitoring chatbot using Claude Sonnet 4.5 via AWS Bedrock.

### 2. How does it work?
```
User asks a question
    ↓
Claude decides which analytics function to call (20 options)
    ↓
Function queries DuckDB (90+ SLO metrics)
    ↓
Results stream to Claude for synthesis
    ↓
Formatted response shown to user
```

### 3. Key Technologies
- **UI:** Streamlit (Python web framework)
- **LLM:** Claude Sonnet 4.5 via AWS Bedrock (function calling)
- **Database:** DuckDB (OLAP - for time-series SLO data, not vector DB)
- **Data Source:** WM Platform API (Keycloak OAuth2)
- **Analytics:** 20 Python functions organized by type

### 4. The 20 Analytics Functions

**Performance Basics (6)**
- `get_degrading_services()` - Week-over-week decline
- `get_current_sli()` - Service Level Indicators
- `get_slo_violations()` - Breaching SLOs
- `get_service_health_overview()` - System health snapshot
- `get_top_services_by_volume()` - Highest traffic
- `get_slowest_services()` - P99 latency issues

**Error Budget & Trends (5)**
- `calculate_error_budget()` - Budget consumption
- `get_service_summary()` - Comprehensive per-service
- `predict_issues_today()` - ML predictions
- `get_volume_trends()` - Traffic patterns
- `get_historical_patterns()` - Statistical analysis

**Advanced (8) - NEW Platform API functions**
- `get_services_by_burn_rate()` - Early warning (critical metric)
- `get_aspirational_slo_gap()` - 98% OK but 99% failing
- `get_timeliness_issues()` - Scheduling/batch jobs
- `get_breach_vs_error_analysis()` - Latency vs reliability
- `get_budget_exhausted_services()` - Over 100% consumed
- `get_composite_health_score()` - 0-100 overall score
- `get_severity_heatmap()` - Red vs green indicators
- `get_slo_governance_status()` - SLO approval tracking

**Legacy (1)**
- `get_error_prone_services()` - High error rates

### 5. Database Schema Highlights

**service_logs table (90+ columns)**
- Core: `service_name`, `record_time`, `total_count`, `error_count`
- Response times: `response_time_p50`, `_p95`, `_p99` (critical for latency SLO)
- Error Budget: `eb_allocated`, `eb_consumed`, `eb_left`, `burn_rate`
- Health: `eb_health`, `response_health` (HEALTHY/UNHEALTHY)
- Aspirational: `aspirational_slo`, `aspirational_eb_*`, `aspirational_response_*`
- Advanced: `timeliness_health`, `severity` colors, `slo_status`

**Why DuckDB?** SLO metrics = structured time-series → SQL aggregations, not embeddings

### 6. Data Flow

```
Platform API (Keycloak OAuth2)
    ↓ (90+ fields per service)
DataLoader (parse response)
    ↓ (convert to DataFrame)
DuckDB (insert into service_logs table)
    ↓ (5 indexes for fast queries)
Analytics Functions (execute SQL queries)
    ↓ (filter, group, aggregate)
Claude (receives results as JSON)
    ↓ (formats with template)
User (sees markdown report)
```

### 7. Critical Patterns

**NaN Handling (MUST DO)**
```python
# WRONG - crashes on NaN
value = int(row['total_count'])

# CORRECT - always check
value = int(row['total_count']) if pd.notna(row['total_count']) else 0
```

**Function Adding (3 steps)**
1. Implement in `analytics/metrics.py`
2. Add to `FunctionExecutor` in `function_tools.py`
3. Add to `TOOLS` list in `function_tools.py` (Claude discovers automatically)

**Token Refresh (automatic)**
- Daemon thread refreshes Keycloak token every 4 minutes
- No manual intervention needed

### 8. Configuration

**Must Set (in `.env`)**
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - Bedrock
- `KEYCLOAK_USERNAME` / `KEYCLOAK_PASSWORD` - OAuth2

**Defaults (good to know)**
- Model: `claude-sonnet-4-5-20250929-v1:0`
- Region: `ap-south-1`
- Page size: 200 services per API call
- Max time window: 60 days

### 9. File Locations (Most Important)

| Need | File | Key Function |
|------|------|--------------|
| Run app | `app.py` | `main()` |
| Add analytics | `analytics/metrics.py` | Implement function |
| Change LLM behavior | `agent/claude_client.py` | System prompt in `app.py:135-329` |
| Query database | `data/database/duckdb_manager.py` | `.query(sql)` |
| Load data | `data/ingestion/platform_api_client.py` | `.query_service_health()` |
| Routing | `agent/function_tools.py` | `function_map` dict |

### 10. Running It

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your credentials

# Run
streamlit run app.py

# Test
python test_platform_api.py  # Full test suite
python check_data.py         # Inspect DuckDB
```

### 11. Key Metrics to Know

- **Burn Rate** - How fast error budget is consumed (>2.0 = high risk, >5.0 = critical)
- **EB (Error Budget)** - Percentage of errors allowed before SLO breach
- **P99 Latency** - Most important for latency SLO (not average)
- **Health Status** - HEALTHY/UNHEALTHY (determined by SLO thresholds)
- **Aspirational SLO** - Stricter target (99% vs standard 98%)

### 12. Architecture Decisions

| Decision | Chosen | Why Not Alternative |
|----------|--------|---------------------|
| Database | DuckDB | ClickHouse = overkill, Vector DB = wrong data type |
| LLM Approach | Function Calling | RAG = slower + less transparent + hallucination risk |
| Response | Streaming | Polling = bad UX for multi-tool calls |
| Caching | Streamlit `@cache_resource` | Redis = unnecessary for single server |

### 13. Gotchas

1. **System prompt is HUGE** - 330+ lines in `app.py`, guides Claude's analysis
2. **Data is daily aggregate** - Not hourly, affects query granularity
3. **NaN crashes** - Every analytics function must check `pd.notna()`
4. **Tool calling loops up to 5x** - Claude can call multiple tools in sequence
5. **Conversation history persists** - Clear manually via UI button
6. **Platform API returns 122 services** - Auto-pagination handles this

### 14. Troubleshooting

| Problem | Solution |
|---------|----------|
| Claude won't call tools | Check TOOLS list in `function_tools.py` is passed to `chat_stream()` |
| Crashes on NaN | Add `if pd.notna(value)` checks in analytics functions |
| API 401 (auth failed) | Check `.env` credentials, Keycloak token refresh runs automatically |
| DuckDB "table not found" | Run "Refresh from Platform API" button first to populate data |
| Streamlit cache stale | Delete `__pycache__` and restart: `find . -type d -name __pycache__ -exec rm -r {} +` |

### 15. Testing the System

```bash
# Full Platform API test (includes all 20 functions)
python test_platform_api.py

# Just Keycloak auth
python test_keycloak_auth.py

# Inspect DuckDB
python check_data.py
```

---

## One-Page Architecture Diagram

```
┌──────────────────┐
│  Streamlit UI    │  (app.py)
│   Ask Question   │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────┐
│  Claude Client (claude_client.py)│  AWS Bedrock
│  Streaming Function Calling      │  Max 5 iterations
└────────┬─────────────────────────┘
         │ (decides which tool to call)
         ▼
┌────────────────────────────────────────┐
│  Function Executor (function_tools.py) │  20 functions
│  Routes: tool_name → implementation    │
└────────┬────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Analytics Layer (analytics/*.py)      │  SQL generators
│  MetricsAggregator, SLOCalculator, etc │
└────────┬────────────────────────────────┘
         │ (builds SQL query)
         ▼
┌────────────────────────────────────────┐
│  DuckDB (duckdb_manager.py)            │  OLAP Engine
│  service_logs (90 cols, 5 indexes)     │  Millisecond queries
└────────┬────────────────────────────────┘
         │ (executes SQL)
         ▼
     Results JSON
         │
         ▼
┌──────────────────────────────────────┐
│  Claude Synthesizes (second request) │
│  Formats with markdown template      │
└────────┬──────────────────────────────┘
         │ (streams response)
         ▼
┌──────────────────┐
│  Streamlit UI    │  Formatted
│  Display Result  │  Report
└──────────────────┘
```

---

## Summary: Why This Architecture?

1. **Function Calling** - Claude decides which analysis tool to use (not hallucinated)
2. **DuckDB** - Fast SQL for structured metrics (not ML embeddings)
3. **Streaming** - User sees results being generated in real-time
4. **Statefulness** - Conversation history enables multi-turn analysis
5. **Platform API** - Real SLO data from WM infrastructure
6. **20 Functions** - Covers standard + advanced + Platform API features
7. **90+ Metrics** - Complete coverage of error budgets, health, severity, timeliness

