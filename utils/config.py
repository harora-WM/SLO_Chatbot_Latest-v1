"""Configuration management for the SLO chatbot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

# Helper function to get config values from Streamlit secrets or environment variables
def get_config(key: str, default: str = "") -> str:
    """Get configuration value from Streamlit secrets or environment variables."""
    try:
        import streamlit as st
        # Try Streamlit secrets first (for cloud deployment)
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except (ImportError, FileNotFoundError):
        pass
    # Fall back to environment variables (for local development)
    return os.getenv(key, default)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_DIR = DATA_DIR / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

# Database configuration
DUCKDB_PATH = DATABASE_DIR / "slo_analytics.duckdb"

# AWS Bedrock configuration
AWS_ACCESS_KEY_ID = get_config("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = get_config("AWS_SECRET_ACCESS_KEY")
AWS_REGION = get_config("AWS_REGION", "ap-south-1")
BEDROCK_MODEL_ID = get_config("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")

# OpenSearch configuration
OPENSEARCH_HOST = get_config("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(get_config("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USERNAME = get_config("OPENSEARCH_USERNAME", "admin")
OPENSEARCH_PASSWORD = get_config("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = get_config("OPENSEARCH_USE_SSL", "False").lower() == "true"
OPENSEARCH_INDEX_SERVICE = get_config("OPENSEARCH_INDEX_SERVICE", "hourly_wm_wmplatform_31854")
OPENSEARCH_INDEX_ERROR = get_config("OPENSEARCH_INDEX_ERROR", "hourly_wm_wmplatform_31854_error")

# SLO Thresholds (configurable)
DEFAULT_ERROR_SLO_THRESHOLD = 1.0  # 1% error rate
DEFAULT_RESPONSE_TIME_SLO = 1.0    # 1 second
DEFAULT_SLO_TARGET_PERCENT = 98    # 98% of requests must meet SLO

# Analytics configuration
DEGRADATION_WINDOW_MINUTES = 30
DEGRADATION_THRESHOLD_PERCENT = 20  # 20% increase is considered degradation

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
