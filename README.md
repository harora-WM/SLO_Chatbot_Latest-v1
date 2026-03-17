# SLO Chatbot

AI-powered Service Level Objective (SLO) monitoring and analysis chatbot using Claude Sonnet 4.5 via AWS Bedrock.

## Features

- **Service Health Monitoring**: EB health and response health per service from Platform API
- **Burn Rate Monitoring**: Early warning for SLO violations (>2.0 = high risk, >5.0 = critical)
- **Multi-Tier SLO Tracking**: Standard (98%) and Aspirational (99%) compliance
- **Degradation Detection**: Week-over-week service comparison
- **Error Budget Tracking**: Consumption, breach detection, and remaining budget
- **Conversational Interface**: Natural language queries via Claude Sonnet 4.5
- **Timeliness Tracking**: Batch job and scheduled task performance
- **Composite Health Scoring**: Overall health across 5 dimensions

## Architecture

```
Streamlit UI → Claude Sonnet 4.5 (Bedrock) → 20 Analytics Functions
                                                        │
                                              ┌─────────┴─────────┐
                                         service_logs_eb    service_logs_response
                                              └─────────┬─────────┘
                                                     DuckDB
                                                        │
                                          Platform API (Keycloak OAuth2)
```

**Data Flow:** Platform API → Keycloak auth → PlatformAPIClient (pagination) → DataLoader → DuckDB (2 tables) → Analytics → Claude → User

**Two DuckDB tables:**
- `service_logs_eb` — EB category records: error budget, burn rate, `eb_health`
- `service_logs_response` — RESPONSE category records: response time percentiles, `response_health`

## Setup

1. **Install dependencies**:
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

2. **Configure environment**:
```bash
cp .env.example .env
# Fill in AWS Bedrock, Keycloak, and Platform API values
```

3. **Run**:
```bash
streamlit run app.py
```

## Configuration (`.env`)

```bash
# AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0

# Keycloak OAuth2
KEYCLOAK_URL=https://wm-sandbox-auth-1.watermelon.us/realms/watermelon/protocol/openid-connect/token
KEYCLOAK_USERNAME=...
KEYCLOAK_PASSWORD=...
KEYCLOAK_CLIENT_ID=web_app

# Platform API
PLATFORM_API_URL=https://wm-sandbox-1.watermelon.us/services/wmerrorbudgetstatisticsservice/api/transactions/distinct/top-5/ALL
PLATFORM_API_APPLICATION=WMPlatform
PLATFORM_API_APPLICATION_ID=31854
PLATFORM_API_PROJECT_ID=215853
PLATFORM_API_PAGE_SIZE=200
PLATFORM_API_VERIFY_SSL=False
```

## Usage

1. Open `http://localhost:8501`
2. Select a time range (5 / 7 / 15 / 30 / 60 days or custom)
3. Click **Refresh from Platform API** to load data
4. Ask Claude questions in the chat

**Sample questions:**
- "Which services have high burn rates?"
- "Show services violating their SLO"
- "What are the slowest services by P99?"
- "Show composite health scores"
- "Which services have exhausted their error budget?"
- "Show the severity heatmap"

## Analytics Functions (20)

**Health & Performance (7):** `get_service_health_overview`, `get_degrading_services`, `get_slo_violations`, `get_slowest_services`, `get_top_services_by_volume`, `get_service_summary`, `get_current_sli`

**Platform API Advanced (8):** `get_services_by_burn_rate`, `get_aspirational_slo_gap`, `get_timeliness_issues`, `get_breach_vs_error_analysis`, `get_budget_exhausted_services`, `get_composite_health_score`, `get_severity_heatmap`, `get_slo_governance_status`

**Trends & Predictions (5):** `calculate_error_budget`, `get_volume_trends`, `predict_issues_today`, `get_historical_patterns`, `get_error_prone_services`

## Testing

```bash
python test_keycloak_auth.py   # Test Keycloak OAuth2
python test_platform_api.py    # Test Platform API + all 20 analytics functions
```

## Docker

```bash
docker build -t slo-chatbot .
docker run -p 8501:8501 --env-file .env slo-chatbot
```
