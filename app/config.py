import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API information
API_VERSION = "1.0.0"
API_DESCRIPTION = """
An optimized, unofficial API for albumoftheyear.org.

This API provides access to album information, user profiles, and more from 
albumoftheyear.org with improved performance, caching, and additional features.
"""

# Base URL for albumoftheyear.org
BASE_URL = "https://www.albumoftheyear.org"

# Browser headers to use for requests
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
}

# Redis configuration
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

# Check if Redis environment variables are set
if not REDIS_URL or not REDIS_TOKEN:
    print("⚠️ Warning: Redis configuration missing. Cache will be disabled.")
    # You could set up a fallback cache mechanism here

# Playwright configuration
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT = 30000  # milliseconds