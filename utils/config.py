"""Configuration management for the SLO chatbot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file (for local dev only)
load_dotenv()

def get_config(key: str, default: str = "") -> str:
    return os.getenv(key, default)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_DIR = DATA_DIR / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

# Database
DUCKDB_PATH = DATABASE_DIR / "slo_analytics.duckdb"

# AWS Bedrock
AWS_ACCESS_KEY_ID = get_config("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = get_config("AWS_SECRET_ACCESS_KEY")
AWS_REGION = get_config("AWS_REGION", "ap-south-1")
BEDROCK_MODEL_ID = get_config(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

# OpenSearch
OPENSEARCH_HOST = get_config("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(get_config("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USERNAME = get_config("OPENSEARCH_USERNAME", "admin")
OPENSEARCH_PASSWORD = get_config("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = get_config("OPENSEARCH_USE_SSL", "False").lower() == "true"

# Keycloak
KEYCLOAK_URL = get_config("KEYCLOAK_URL")
KEYCLOAK_USERNAME = get_config("KEYCLOAK_USERNAME")
KEYCLOAK_PASSWORD = get_config("KEYCLOAK_PASSWORD")
KEYCLOAK_CLIENT_ID = get_config("KEYCLOAK_CLIENT_ID", "web_app")

# Platform API
PLATFORM_API_URL = get_config("PLATFORM_API_URL")
PLATFORM_API_APPLICATION = get_config("PLATFORM_API_APPLICATION", "WMPlatform")
PLATFORM_API_PAGE_SIZE = int(get_config("PLATFORM_API_PAGE_SIZE", "200"))
PLATFORM_API_VERIFY_SSL = get_config("PLATFORM_API_VERIFY_SSL", "False").lower() == "true"

# Time window config
DEFAULT_TIME_WINDOW_DAYS = int(get_config("DEFAULT_TIME_WINDOW_DAYS", "5"))
MAX_TIME_WINDOW_DAYS = int(get_config("MAX_TIME_WINDOW_DAYS", "60"))

LOG_LEVEL = get_config("LOG_LEVEL", "INFO")