# SLO Chatbot Architecture Analysis

**Project:** SLO_Chatbot_Latest-v1 (Location: `/home/hardik121/SLO_Chatbot_Latest-v1`)  
**Status:** Platform API migration complete (Jan 2026)  
**Tech Stack:** Streamlit + DuckDB + Claude Sonnet 4.5 via AWS Bedrock + WM Platform API

---

## 1. CURRENT ARCHITECTURE OVERVIEW

### 1.1 Data Flow Pipeline
```
User Query
    ↓
Streamlit UI (app.py)
    ↓
Claude Client (claude_client.py)
    ↓
LLM Function Calling (Claude → 20 Analytics Tools)
    ↓
Function Executor (function_tools.py)
    ↓
Analytics Layer (MetricsAggregator, SLOCalculator, etc.)
    ↓
DuckDB (OLAP) ← Populated by Platform API
    ↓
User Response (Streamed)
```

### 1.2 Component Stack
- **UI Layer:** Streamlit (Python web framework)
- **LLM Integration:** Claude Sonnet 4.5 via AWS Bedrock (function calling)
- **Data Store:** DuckDB (not a vector DB - structured OLAP for time-series SLO data)
- **Data Source:** WM Platform API (Keycloak OAuth2 authenticated)
- **Analytics:** Python modules (SLOCalculator, MetricsAggregator, DegradationDetector, TrendAnalyzer)

---

## 2. LLM INTEGRATION (Claude Sonnet 4.5 via AWS Bedrock)

### 2.1 Claude Client (`agent/claude_client.py`)
**Key Responsibilities:**
- Manages conversation history across requests
- Invokes AWS Bedrock API with function calling
- Handles multi-turn tool use (max 5 iterations)
- Supports both regular and streaming responses
- Auto-refreshes tokens every 4 minutes

**Key Methods:**
- `chat()` - Complete interaction with tool support
- `chat_stream()` - Streaming response generation for real-time UI updates
- `send_message()` - Raw message to Claude
- `handle_tool_use()` - Processes Claude's tool invocations
- `clear_history()` - Reset conversation

**Flow Example:**
```python
# User asks: "Which services have high burn rates?"
response = claude_client.chat_stream(
    user_message="Which services have high burn rates?",
    tools=TOOLS,  # 20 function definitions
    tool_executor=function_executor,
    system_prompt=COMPREHENSIVE_SLO_SYSTEM_PROMPT
)
# Claude decides to call: get_services_by_burn_rate(limit=10)
# Function executes, results returned to Claude
# Claude synthesizes response and streams back to user
```

### 2.2 Model Configuration
- **Model:** `global.anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Max Tokens:** 8192
- **Temperature:** 0.7
- **Timeout:** 5 minutes (read), 10 seconds (connect)
- **Retries:** 2 attempts
- **Region:** ap-south-1 (configurable)

### 2.3 System Prompt Architecture
**Massive system prompt** (330+ lines in `app.py:135-329`) covering:
- SLO metrics structure (90+ fields)
- Multi-tier SLO tracking (standard 98%, aspirational 99%)
- Error budget mechanics
- Available 20 analytics functions
- Output format (strict markdown template)
- Important behavior rules (use P99, check burn rate, distinguish breach vs error)
- Example good/bad analyses

---

## 3. HELPER TOOLS & ANALYTICS FUNCTIONS

### 3.1 20 Available Analytics Functions

**Defined in:** `agent/function_tools.py` (lines 197-484)

**Categories:**

#### A. Standard Performance & Health (6 functions)
1. `get_degrading_services()` - Week-over-week comparison
2. `get_current_sli()` - Current Service Level Indicators
3. `get_slo_violations()` - Services violating SLO
4. `get_service_health_overview()` - System-wide health summary
5. `get_top_services_by_volume()` - High-traffic services
6. `get_slowest_services()` - P99 latency ranking

#### B. SLO & Budget Tracking (2 functions)
7. `calculate_error_budget()` - Error budget consumption
8. `get_service_summary()` - Comprehensive per-service analysis

#### C. Trend Analysis (3 functions)
9. `predict_issues_today()` - ML predictions (linear regression, 2+ weeks)
10. `get_volume_trends()` - Traffic patterns over time
11. `get_historical_patterns()` - Statistical analysis

#### D. Platform API Advanced (8 functions)
12. `get_services_by_burn_rate()` - Proactive SLO risk monitoring
13. `get_aspirational_slo_gap()` - 98% compliant but 99% failing
14. `get_timeliness_issues()` - Batch job/scheduling problems
15. `get_breach_vs_error_analysis()` - Latency vs reliability distinction
16. `get_budget_exhausted_services()` - Over 100% consumed
17. `get_composite_health_score()` - 0-100 across 5 dimensions
18. `get_severity_heatmap()` - Red vs green indicators
19. `get_slo_governance_status()` - SLO approval tracking

Plus legacy (deprecated):
20. `get_error_code_distribution()` - Not available with Platform API
21. `get_error_prone_services()` - Error rate ranking
22. `get_top_errors()` - Most common error codes
23. `get_error_details_by_code()` - Detailed error logs

### 3.2 Function Executor (`agent/function_tools.py`)

**Purpose:** Dispatcher that maps tool names to analytics functions

```python
class FunctionExecutor:
    def execute(function_name: str, parameters: Dict) -> Any:
        # Routes to appropriate analytics function
        # Handles parameter validation
        # Returns JSON-serializable results
```

**Key Pattern:**
```python
function_map = {
    "get_services_by_burn_rate": self._get_services_by_burn_rate,
    "get_aspirational_slo_gap": self._get_aspirational_slo_gap,
    # ... 18 more functions
}
```

---

## 4. DATABASE INTERACTION (DuckDB)

### 4.1 Database Manager (`data/database/duckdb_manager.py`)

**Why DuckDB (not ClickHouse/Vector DB)?**
- SLO data is structured time-series (not unstructured text)
- SQL aggregations >> semantic search for metrics
- Supports OLAP queries efficiently
- Lightweight, embedded (no separate server)

**Database Path:** `data/database/slo_analytics.duckdb`

### 4.2 Schema: `service_logs` Table (90+ columns)

**Core Fields (5):**
- `id`, `app_id`, `sid`, `service_name`, `record_time`

**Volume & Reliability (6):**
- `total_count`, `success_count`, `error_count`, `success_rate`, `error_rate`, `total_data_points`

**Response Time Percentiles (11):**
- `response_time_avg`, `_min`, `_max`, `_p25`, `_p50`, `_p75`, `_p80`, `_p85`, `_p90`, `_p95`, `_p99`

**Standard SLO (3):**
- `target_error_slo_perc`, `target_response_slo_sec`, `response_target_percent`

**Standard Error Budget (7):**
- `eb_allocated_percent`, `_count`, `eb_consumed_percent`, `_count`, `eb_actual_consumed_percent`, `eb_left_percent`, `_count`

**Standard Response Budget (7):**
- `response_allocated_percent`, `_count`, `response_consumed_percent`, `_count`, `response_actual_consumed_percent`, `response_left_percent`, `_count`

**Aspirational SLO Metrics (15):**
- `aspirational_slo`, `aspirational_eb_*` (8 fields), `aspirational_response_*` (7 fields)

**Health Indicators (6):**
- `eb_health`, `response_health`, `aspirational_eb_health`, `aspirational_response_health`, `timeliness_health`, `eb_or_response_breached`

**Severity Colors (4):**
- `response_severity`, `eb_severity`, `aspirational_response_severity`, `aspirational_eb_severity`

**Advanced Metrics (3):**
- `burn_rate` (critical for early warning), `eb_breached`, `eb_slo_status`

**Metadata (4):**
- `sort_data`, `data_for`, `timezone`, `sre_product`

### 4.3 Indexes (5)
- `idx_service_time` - Time-based queries
- `idx_service_name` - Service filtering
- `idx_burn_rate` - High-risk identification
- `idx_eb_health` - Health-based filtering
- `idx_response_health`, `idx_eb_breached` - Multi-dimensional filtering

### 4.4 Key Methods

**Query Interface:**
```python
db_manager.query(sql)              # Execute SQL, return DataFrame
db_manager.insert_service_logs(df) # Batch insert 90+ cols
db_manager.get_all_services()      # List unique services
db_manager.get_time_range()        # Min/max timestamps
db_manager.get_service_logs()      # Filtered query with time window
```

**Example Query (from get_services_by_burn_rate):**
```sql
SELECT
    service_name,
    AVG(burn_rate) as avg_burn_rate,
    AVG(eb_actual_consumed_percent) as avg_eb_consumed,
    AVG(eb_left_percent) as avg_eb_left,
    MAX(eb_health) as eb_health
FROM service_logs
GROUP BY service_name
HAVING avg_burn_rate > 0
ORDER BY avg_burn_rate DESC
LIMIT 10
```

---

## 5. DATA FLOW: User Query → LLM → Tool → Database

### 5.1 Complete Interaction Flow

```
1. USER INPUT (Streamlit)
   ├─ User types: "Show services with high burn rates"
   └─ Sent to: claude_client.chat_stream()

2. CLAUDE REQUEST #1
   ├─ Receives: user message, TOOLS (20 function definitions), system_prompt
   ├─ Bedrock API call: invoke_model_with_response_stream()
   └─ Claude decides: "I need to call get_services_by_burn_rate(limit=10)"

3. TOOL INVOCATION
   ├─ Stop reason: "tool_use"
   ├─ Tool name: "get_services_by_burn_rate"
   ├─ Parameters: {"limit": 10}
   └─ Sent to: function_executor.execute()

4. ANALYTICS EXECUTION
   ├─ Function: MetricsAggregator.get_services_by_burn_rate(limit=10)
   ├─ SQL Query on DuckDB:
   │  SELECT service_name, AVG(burn_rate), AVG(eb_consumed), ...
   │  GROUP BY service_name
   │  ORDER BY avg_burn_rate DESC LIMIT 10
   └─ Returns: List[Dict] with 10 services sorted by burn rate

5. RESULT PROCESSING
   ├─ Serialize: JSON via DateTimeEncoder (handles NaN, datetime, numpy)
   ├─ Validation: Empty result → {"message": "No data found"}
   └─ Add to history: tool_result message

6. CLAUDE REQUEST #2 (Follow-up)
   ├─ Receives: tool results + original system_prompt + TOOLS (for multi-turn)
   ├─ Bedrock API call: invoke_model_with_response_stream()
   ├─ Claude synthesizes: Formats results according to output template
   ├─ Stream chunks to user in real-time
   └─ Stop reason: "end_turn" (no more tool calls needed)

7. RESPONSE COMPLETE
   ├─ Claude returns: Formatted markdown report
   ├─ UI streaming complete
   └─ Both stored in conversation_history for context

8. CHAT HISTORY MAINTAINED
   ├─ Stores: [user_msg, assistant_content, tool_results, assistant_response]
   ├─ Used for: Multi-turn conversations, context awareness
   └─ Cleared: When user clicks "Clear Chat History" button
```

### 5.2 Error Handling

**At Each Stage:**
1. **Bedrock API Error** → Logged, re-raised
2. **Tool Execution Error** → Caught, returned as `{"error": str(e)}`
3. **Empty Results** → Converted to `{"message": "No data found"}`
4. **NaN Values** → Checked with `pd.notna()` before conversion
5. **Max Iterations** → Logged warning, stops at 5 tool calls

---

## 6. CACHING MECHANISMS

### 6.1 Streamlit Caching

**Location:** `app.py:54-99` in `initialize_system()` function

```python
@st.cache_resource
def initialize_system():
    # All components initialized ONCE per session
    db_manager = DuckDBManager()
    auth_manager = KeycloakAuthManager()
    api_client = PlatformAPIClient(auth_manager)
    slo_calculator = SLOCalculator(db_manager)
    # ... more components
    
    return {
        'db_manager': db_manager,
        'claude_client': claude_client,
        # ... all components
    }
```

**Benefits:**
- Database connection persists across requests
- Auth tokens refreshed automatically (4-min daemon thread)
- Analytics components reused
- Significant performance improvement

### 6.2 Keycloak Token Refresh

**Location:** `data/ingestion/keycloak_auth.py`

```python
# Daemon thread refreshes access token every 4 minutes
KEYCLOAK_TOKEN_REFRESH_INTERVAL = 240  # seconds
```

**Auto-Refresh Pattern:**
- Background thread manages token lifecycle
- Fresh token always available via `get_access_token()`
- Prevents mid-request authentication failures

### 6.3 No Additional Caching

- **No Redis:** Not needed (local session cache sufficient)
- **No Query Caching:** Each query reflects current data
- **Conversation History:** In-memory, cleared on user request

---

## 7. MAIN ENTRY POINTS & KEY FILES

### 7.1 Entry Points

**Primary:**
- `app.py` - Streamlit web UI (run: `streamlit run app.py`)

**Testing:**
- `test_platform_api.py` - Full Platform API test suite
- `test_keycloak_auth.py` - OAuth2 authentication only
- `check_data.py` - DuckDB inspection

### 7.2 Key File Structure

```
/home/hardik121/SLO_Chatbot_Latest-v1/
├── app.py                              # Streamlit UI + chat interface
├── requirements.txt                    # Dependencies
├── .env                               # Config (AWS Bedrock, Keycloak, Platform API)
│
├── agent/
│   ├── claude_client.py               # Bedrock API client + conversation mgmt
│   └── function_tools.py              # 20 analytics functions + tool definitions
│
├── data/
│   ├── database/
│   │   └── duckdb_manager.py          # DuckDB OLAP engine (90+ cols)
│   └── ingestion/
│       ├── keycloak_auth.py           # OAuth2 token management
│       ├── platform_api_client.py     # API fetch + auto-pagination
│       └── data_loader.py             # Parse API response → DataFrame
│
├── analytics/
│   ├── slo_calculator.py              # Error budgets, burn rates
│   ├── degradation_detector.py        # Week-over-week comparison
│   ├── trend_analyzer.py              # Predictions (linear regression)
│   └── metrics.py                     # 20 analytics functions
│
└── utils/
    ├── config.py                      # Configuration mgmt
    └── logger.py                      # Logging setup
```

### 7.3 Critical File Details

| File | Purpose | Lines | Key Functions |
|------|---------|-------|----------------|
| `app.py` | Streamlit UI | 510 | `initialize_system()`, `display_chat()`, `main()` |
| `claude_client.py` | LLM integration | 476 | `chat_stream()`, `handle_tool_use()`, `send_message()` |
| `function_tools.py` | Analytics dispatcher | 485 | `execute()`, 20 `_get_*()` methods, TOOLS list |
| `duckdb_manager.py` | Database | 450+ | `query()`, `insert_service_logs()`, schema definition |
| `platform_api_client.py` | Data ingestion | 250+ | `query_service_health()`, `_fetch_page()` |
| `metrics.py` | Analytics | 700+ | 20 function implementations (burn rate, aspirational, etc.) |
| `config.py` | Configuration | 85 | Environment + Streamlit secrets handling |

---

## 8. QUERY FLOW: DETAILED EXAMPLE

**User Asks:** "Which services are at risk of SLO breach?"

### Step-by-Step Execution:

```python
# 1. Claude parses query, decides to call get_aspirational_slo_gap()
# (meeting 98% but failing 99%)

# 2. Function executor routes to:
result = metrics_aggregator.get_aspirational_slo_gap()

# 3. Inside get_aspirational_slo_gap() (metrics.py:349-389):
sql = """
    SELECT
        service_name,
        eb_health,
        aspirational_eb_health,
        response_health,
        aspirational_response_health,
        AVG(eb_actual_consumed_percent) as std_eb_consumed,
        AVG(aspirational_eb_actual_consumed_percent) as asp_eb_consumed,
        AVG(burn_rate) as avg_burn_rate
    FROM service_logs
    WHERE (eb_health = 'HEALTHY' AND aspirational_eb_health = 'UNHEALTHY')
       OR (response_health = 'HEALTHY' AND aspirational_response_health = 'UNHEALTHY')
    GROUP BY service_name, eb_health, aspirational_eb_health,
             response_health, aspirational_response_health
"""

# 4. DuckDB executes SQL on service_logs table
df = db_manager.query(sql)

# 5. Post-process with NaN safety:
for _, row in df.iterrows():
    result.append({
        'service_name': row['service_name'],
        'eb_health': row['eb_health'],
        'aspirational_eb_health': row['aspirational_eb_health'],
        'std_eb_consumed': row['std_eb_consumed'] if pd.notna(row['std_eb_consumed']) else 0.0,
        # ... more fields
    })

# 6. Return to Claude as JSON
# 7. Claude synthesizes into formatted response with markdown template
# 8. Stream to user in real-time
```

---

## 9. ARCHITECTURE DECISIONS & TRADEOFFS

### 9.1 Why DuckDB (not ClickHouse/Vector DB)?

| Aspect | DuckDB | ClickHouse | Vector DB |
|--------|--------|-----------|-----------|
| **Data Type** | Structured time-series | Structured analytics | Unstructured text |
| **Query Type** | SQL aggregations | SQL OLAP | Semantic search |
| **Use Case Fit** | 100% ✅ | 90% | 10% ❌ |
| **Deployment** | Embedded file | Server required | Server required |
| **Complexity** | Low | Medium | Medium |

**Verdict:** SLO metrics need SQL GROUP BY, AVG(), SUM() - not embeddings.

### 9.2 Claude Function Calling vs RAG

**Function Calling (Chosen):**
- ✅ Tools are deterministic functions with fixed signatures
- ✅ No hallucination risk (Claude can't invent functions)
- ✅ Multi-turn support (loop until tool_use stops)
- ✅ Structured output from tools

**RAG Alternative (Not Used):**
- ❌ Would require embedding 90 metrics into vector space
- ❌ Semantic similarity not relevant for SLO queries
- ❌ Increases latency (retrieval + generation)
- ❌ Less transparent (black box similarity scores)

### 9.3 Streaming vs Non-Streaming

**Streaming (Chosen in app.py:346):**
- ✅ Real-time user feedback during long analyses
- ✅ Better UX for multi-tool calls
- ✅ Reduces perceived latency
- ❌ More complex implementation

**Non-Streaming:**
- ❌ UI feels slow on 2-3 tool calls
- ❌ User must wait for complete response

---

## 10. MIGRATION HISTORY & DEPRECATIONS

### 10.1 From OpenSearch (Deprecated) → Platform API

**OpenSearch (deprecated):**
- Hourly granularity (limited to 24 hours)
- Index size limitations
- ~30 fields only
- Real-time but limited history

**Platform API (current):**
- Daily aggregation (5-60 day windows)
- 90+ fields including burn rate, health indicators, aspirational SLO
- Unlimited pagination
- Structured response with governance data

**Deprecated Files:**
- `data/ingestion/opensearch_client.py` - No longer used
- `debug_opensearch.py` - Debugging only
- References in DEPRECATED.md

### 10.2 Critical Bug Fix (Jan 2026)

**Historical Bug:** Only loaded 1 service (misunderstood API response)

```python
# ❌ WRONG (old code)
return data  # Treated entire response as 1 service

# ✅ CORRECT (fixed in platform_api_client.py:186-190)
if 'summary' in data and isinstance(data['summary'], list):
    return data['summary']  # Returns all services
```

---

## 11. CONFIGURATION

### 11.1 Environment Variables (via `.env`)

```bash
# AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1  # Default
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0  # Default

# Keycloak OAuth2
KEYCLOAK_URL=https://wm-sandbox-auth-1.watermelon.us/realms/watermelon/protocol/openid-connect/token
KEYCLOAK_USERNAME=wmadmin
KEYCLOAK_PASSWORD=...

# Platform API
PLATFORM_API_URL=https://wm-sandbox-1.watermelon.us/services/wmerrorbudgetstatisticsservice/api/v1/services/health
PLATFORM_API_PAGE_SIZE=200

# Database
DUCKDB_PATH=data/database/slo_analytics.duckdb

# Logging
LOG_LEVEL=INFO
```

### 11.2 Hard-Coded Constants (in `utils/config.py`)

```python
DEFAULT_TIME_WINDOW_DAYS = 5
MAX_TIME_WINDOW_DAYS = 60
DEGRADATION_THRESHOLD_PERCENT = 20
DEFAULT_ERROR_SLO_THRESHOLD = 1.0  # 1% error
ASPIRATIONAL_SLO_TARGET_PERCENT = 99
```

---

## 12. PERFORMANCE CONSIDERATIONS

### 12.1 Query Performance

**DuckDB Strengths:**
- Parquet-optimized OLAP queries
- Vectorized execution (columns in memory)
- Index scans on health/burn_rate columns
- Sub-100ms for typical aggregations

**Optimization Tips:**
- Use `get_all_services()` to cache service list
- Filter by time_window early (indexed on record_time)
- Use `HAVING` clause (post-group filtering)

### 12.2 API Pagination

**Auto-Pagination (platform_api_client.py:80-110):**
- Fetches 200 services per page (configurable)
- Loops until `len(page) < page_size`
- Handles errors gracefully (partial data > no data)
- Logs progress: "Page 0: Fetched 200 services | Total: 200"

### 12.3 Token Refresh

**Keycloak (keycloak_auth.py):**
- Daemon thread refreshes every 4 minutes
- No mid-request authentication failures
- `get_access_token()` always returns fresh token

---

## 13. COMMON WORKFLOWS

### 13.1 Load Data from Platform API

```python
# app.py:400-445
auth_manager = KeycloakAuthManager()
api_client = PlatformAPIClient(auth_manager)

# Fetch last 7 days
start_time_ms = int((now - timedelta(days=7)).timestamp() * 1000)
end_time_ms = int(now.timestamp() * 1000)

api_response = api_client.query_service_health(start_time_ms, end_time_ms)
# Returns: List[Dict] with 122 services, 90+ fields each

df = data_loader.load_service_logs_from_platform_api(api_response)
db_manager.insert_service_logs(df)
```

### 13.2 Ask Claude a Question

```python
# app.py:346-357
full_response = ""
for chunk in claude_client.chat_stream(
    user_message="Which services have high burn rates?",
    tools=TOOLS,
    tool_executor=function_executor,
    system_prompt=system_prompt
):
    full_response += chunk
    response_placeholder.markdown(full_response + "▌")

response_placeholder.markdown(full_response)  # Final
```

### 13.3 Add New Analytics Function

**Steps:**
1. Implement in `analytics/metrics.py` (e.g., `get_my_metric()`)
2. Add to `FunctionExecutor._get_my_metric()` wrapper
3. Add tool definition to `TOOLS` list in `function_tools.py`
4. Reference in system prompt `app.py:200-230`
5. Claude auto-discovers via TOOLS list

---

## 14. TESTING & DEBUGGING

### 14.1 Test Platform API Connection

```bash
python test_platform_api.py
# Tests: Keycloak auth + Platform API + All 20 functions
```

### 14.2 Inspect DuckDB

```bash
python check_data.py
# Shows: Row counts, service names, time ranges
```

### 14.3 Debug Streamlit Cache Issues

```bash
find . -type d -name "__pycache__" -exec rm -r {} + && streamlit run app.py
# Clears cache, restarts Streamlit
```

---

## 15. SUMMARY: Query Path Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                        │
│                    User Types Question                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Claude Client (claude_client.py)                   │
│  Sends: user_message + TOOLS (20 functions) + system_prompt     │
│  Via: AWS Bedrock (region: ap-south-1)                          │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  Claude Decides to Call Tool(s)    │
        │  E.g., get_services_by_burn_rate() │
        └────────────────┬───────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│          Function Executor (agent/function_tools.py)            │
│          Routes: tool_name → implementation function            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│      Analytics Layer (analytics/metrics.py)                     │
│      E.g., MetricsAggregator.get_services_by_burn_rate()        │
│      Builds SQL query with filters, joins, aggregations         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             DuckDB (data/database/duckdb_manager.py)            │
│             Table: service_logs (90+ columns)                   │
│             Executes: SELECT, GROUP BY, ORDER BY LIMIT          │
│             Returns: DataFrame with results                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
      ┌──────────────────────────────────┐
      │   Post-Process Results           │
      │  - Handle NaN values             │
      │  - Convert to JSON (DateTimeEncoder) │
      │  - Validate non-empty            │
      └──────────────────┬───────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│         Claude Client (Second Request)                          │
│         Receives: tool_results                                  │
│         Synthesizes: Natural language response                  │
│         Streams: Text chunks to user                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit UI (Rendering)                     │
│                    Displays: Formatted markdown                 │
│                    Stores: Conversation history                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 16. KEY INSIGHTS FOR DEVELOPMENT

1. **System Prompt is Critical:** 330+ lines guide Claude's analysis
2. **NaN Handling is Essential:** Every analytics function must check `pd.notna()`
3. **DuckDB is Perfect for This:** Structured time-series → SQL, not embeddings
4. **Streaming Matters:** Real-time feedback in UI improves perceived performance
5. **Tool Calling > RAG:** Deterministic functions > semantic search for metrics
6. **Conversation History:** Enables multi-turn analysis without starting over
7. **Cache @ Streamlit Level:** `@st.cache_resource` not needed in analytics
8. **Token Auto-Refresh:** 4-min daemon prevents auth failures mid-request
9. **Daily Granularity:** Data is aggregated daily (not hourly) - key for queries
10. **90+ Metrics:** Schema covers all SLO dimensions (error budget, timeliness, severity, etc.)

