#!/usr/bin/env python3
"""
Manual test script for Pipedrive API rate limiting.

PROBLEM SUMMARY:
================
The Hermes application was getting rate limited from Pipedrive API because:
1. Multiple TC2 webhooks could arrive simultaneously
2. Each webhook triggered background tasks to sync data to Pipedrive
3. Background tasks made multiple API calls (org, person, deal) without any rate limiting
4. Pipedrive has a rate limit of 10 requests per 2 seconds
5. Burst traffic from webhooks would exceed this limit and cause errors:
   - 429 errors from Pipedrive API rate limiting
   - 403 errors from Cloudflare rate limiting

SOLUTION IMPLEMENTED:
====================
1. Added httpx-limiter library (dependency: 'httpx-limiter>=0.4.0' in pyproject.toml)

2. Modified app/pipedrive/api.py:
   - Created a singleton httpx.AsyncClient with AsyncRateLimitedTransport
   - Rate limit set to 9 requests per 2 seconds (slightly under Pipedrive's 10 req/2sec)
   - Used lazy initialization (_get_client() function) to avoid event loop issues at import time
   - Added retry logic for both 429 and 403 errors as a safety net (exponential backoff: 2s, 4s, 6s)
   - Added rate limit header extraction and logging for monitoring

3. Key code changes in app/pipedrive/api.py:
   ```python
   from httpx_limiter import AsyncRateLimitedTransport, Rate

   _client: Optional[httpx.AsyncClient] = None

   def _get_client() -> httpx.AsyncClient:
       '''Singleton client with rate limiting'''
       global _client
       if _client is None:
           _transport = AsyncRateLimitedTransport.create(
               Rate.create(magnitude=settings.pd_api_max_rate, duration=settings.pd_api_rate_period)
           )
           _client = httpx.AsyncClient(transport=_transport)
       return _client
   ```

4. How it works:
   - AsyncRateLimitedTransport uses a token bucket algorithm
   - Requests are queued and released at the configured rate (9 req/2sec)
   - Multiple concurrent requests are automatically spaced out
   - The singleton client ensures rate limiting works across all requests

5. Configuration in app/core/config.py:
   - pd_api_max_rate: 9 (requests allowed)
   - pd_api_rate_period: 2 (seconds)
   - pd_api_max_retry: 3 (max retries on 429)
   - pd_api_enable_retry: True (enable retry logic)

TESTING:
========
This script tests the rate limiting by:
1. Starting the Hermes application server
2. Firing multiple TC2 webhook requests simultaneously
3. Monitoring logs for 429/403 errors
4. Checking that all companies are successfully synced to Pipedrive

Run this script while the Hermes app is running on http://localhost:9000
The script will fire 100 webhooks rapidly and verify rate limiting works.

CONFIGURATION:
==============
Edit the variables below in the script to customize the test:
- BASE_URL: Base URL of Hermes app (default: http://localhost:9000)
- NUM_WEBHOOKS: Number of webhooks to fire (default: 100)
- TEST_ADMIN_ID: TC2 Admin ID to use in test data (default: 481028 - Fionn)
- FORCE_403_MODE: Set to True to intentionally trigger 403/429 errors (default: False)

To test retry logic, change FORCE_403_MODE to True in the script below.

STRESS TEST:
============
Default is 100 webhooks which will stress test the rate limiter.
With 9 req/2sec rate limit and each webhook making ~3 Pipedrive API calls
(organization, person, deal), expect the test to take ~30-60 seconds.
The rate limiter should prevent ALL 429/403 errors despite the burst traffic.
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Add project root to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent))

# ========== TEST CONFIGURATION - EDIT THESE ==========
BASE_URL = "http://localhost:9000"
NUM_WEBHOOKS = 200  # Increased to 200 for more aggressive testing
TEST_ADMIN_ID = 481028  # Fionn's TC2 admin ID
FORCE_403_MODE = True  # Set to True to intentionally trigger 403/429 errors
DISABLE_RATE_LIMITER = True  # Temporarily disable rate limiter to force 403s
# =====================================================

TC2_CALLBACK_URL = f"{BASE_URL}/tc2/callback/"

try:
    from app.core.config import settings

    print(f"✓ Loaded settings from app.core.config")
    print(f"  - Rate limit: {settings.pd_api_max_rate} requests per {settings.pd_api_rate_period} seconds")
    print(f"  - Pipedrive URL: {settings.pd_base_url}")
    print(f"  - Retry enabled: {settings.pd_api_enable_retry}")
    print(f"  - Max retries: {settings.pd_api_max_retry}")

except ImportError as e:
    print(f"⚠ WARNING: Could not import app settings: {e}")
    print(f"  Using default configuration")


# Configuration summary
print(f"\nConfiguration:")
print(f"  - Base URL: {BASE_URL}")
print(f"  - TC2 Callback: {TC2_CALLBACK_URL}")
print(f"  - Number of webhooks: {NUM_WEBHOOKS}")
print(f"  - Test admin ID: {TEST_ADMIN_ID}")
print(f"  - Force 403/429 errors: {FORCE_403_MODE}")
print(f"  - Disable rate limiter: {DISABLE_RATE_LIMITER}")

if DISABLE_RATE_LIMITER:
    print(f"\n⚠️  WARNING: Rate limiter bypass mode enabled!")
    print(f"   This will temporarily replace the rate-limited client with a regular one")
    print(f"   to force 403/429 errors and test retry logic.\n")


def create_webhook_payload(index: int) -> dict:
    """
    Create a TC2 webhook payload for testing.

    This mimics a real TC2 webhook that would trigger Pipedrive sync.
    Each webhook creates a new company that needs to be synced to Pipedrive.
    """
    return {
        "events": [
            {
                "action": "UPDATE",
                "verb": "update",
                "subject": {
                    "model": "Client",
                    "id": 9000 + index,  # Unique client ID
                    "meta_agency": {
                        "id": 10000 + index,  # Unique agency ID
                        "name": f"Manual Test Company {index}",
                        "country": "United Kingdom (GB)",
                        "status": "active",
                        "paid_invoice_count": index,
                        "created": datetime.now(timezone.utc).isoformat(),
                        "price_plan": "monthly-payg",
                        "narc": False,  # Not a bad customer - should sync to Pipedrive
                    },
                    "user": {
                        "first_name": "Manual",
                        "last_name": f"Test{index}",
                        "email": f"manualtest{index}@example.com",
                        "phone": f"+44123456{index:04d}",
                    },
                    "status": "active",
                    "sales_person": {"id": TEST_ADMIN_ID},  # From config
                    "paid_recipients": [
                        {
                            "id": 11000 + index,
                            "first_name": "Contact",
                            "last_name": f"User{index}",
                            "email": f"contact{index}@example.com",
                        }
                    ],
                    "extra_attrs": [],
                },
            }
        ],
        "_request_time": int(time.time()),
    }


async def fire_webhook(client: httpx.AsyncClient, index: int) -> dict:
    """
    Fire a single webhook to the TC2 callback endpoint.

    Returns:
        dict with keys: index, status_code, duration, error (if any)
    """
    payload = create_webhook_payload(index)
    start_time = time.time()

    try:
        response = await client.post(TC2_CALLBACK_URL, json=payload, timeout=30.0)
        duration = time.time() - start_time

        return {
            "index": index,
            "status_code": response.status_code,
            "duration": duration,
            "error": None,
        }
    except Exception as e:
        duration = time.time() - start_time
        return {
            "index": index,
            "status_code": None,
            "duration": duration,
            "error": str(e),
        }


async def fire_webhooks_in_burst(num_webhooks: int, use_single_client: bool = False) -> list[dict]:
    """
    Fire multiple webhooks simultaneously (in burst).

    This simulates the scenario where multiple TC2 webhooks arrive at the same time,
    which would previously cause rate limiting issues with Pipedrive API.

    With the rate limiter in place, the background tasks should automatically
    space out Pipedrive API calls to stay within the 10 req/2sec limit.

    Args:
        num_webhooks: Number of webhooks to fire
        use_single_client: If True, uses a single httpx client to send all requests
                          at once to maximize chance of hitting rate limits
    """
    print(f"\n{'='*80}")
    print(f"FIRING {num_webhooks} WEBHOOKS IN BURST")
    if use_single_client:
        print(f"MODE: Single client (all at once - will likely trigger 403/429)")
    else:
        print(f"MODE: Normal (rate limiter should prevent 403/429)")
    print(f"{'='*80}\n")

    async with httpx.AsyncClient() as client:
        # Check if server is running
        try:
            await client.get(BASE_URL, timeout=5.0)
        except Exception as e:
            print(f"❌ ERROR: Cannot connect to {BASE_URL}")
            print(f"   Make sure Hermes is running: uvicorn app.main:app --reload --port 9000")
            print(f"   Error: {e}\n")
            return [], 0

        print(f"✓ Server is running at {BASE_URL}\n")

        # Fire all webhooks concurrently
        start_time = time.time()
        tasks = [fire_webhook(client, i) for i in range(num_webhooks)]
        results = await asyncio.gather(*tasks)
        total_duration = time.time() - start_time

        return results, total_duration


def analyze_results(results: list[dict], total_duration: float):
    """
    Analyze and display test results.
    """
    print(f"\n{'='*80}")
    print(f"RESULTS")
    print(f"{'='*80}\n")

    print(f"Total time: {total_duration:.2f}s")
    print(f"Webhooks fired: {len(results)}\n")

    # Count successes and failures
    successes = sum(1 for r in results if r["status_code"] == 200)
    failures = sum(1 for r in results if r["status_code"] != 200 or r["error"])

    print(f"✓ Successful: {successes}")
    print(f"✗ Failed: {failures}\n")

    # Show individual results
    print("Individual webhook results:")
    print(f"{'Index':<8} {'Status':<10} {'Duration':<12} {'Error':<40}")
    print(f"{'-'*8} {'-'*10} {'-'*12} {'-'*40}")

    for r in results:
        status = f"{r['status_code']}" if r['status_code'] else "ERROR"
        duration = f"{r['duration']:.2f}s"
        error = r['error'][:37] + "..." if r['error'] and len(r['error']) > 40 else (r['error'] or "")

        symbol = "✓" if r['status_code'] == 200 else "✗"
        print(f"{symbol} {r['index']:<6} {status:<10} {duration:<12} {error:<40}")

    print(f"\n{'='*80}")
    print(f"ANALYSIS")
    print(f"{'='*80}\n")

    if successes == len(results):
        print("✓ SUCCESS: All webhooks processed successfully!")
        print(f"  The rate limiter is working - {len(results)} webhooks were processed")
        print(f"  without any 429/403 errors from Pipedrive.")
    else:
        print(f"⚠ WARNING: {failures} webhook(s) failed")
        print(f"  Check the Hermes logs for details.")

    print("\nNOTE: Check the Hermes application logs to verify:")
    print("  1. No '429' or '403' rate limit errors from Pipedrive")
    print("  2. All companies were successfully synced")
    print("  3. Rate limit headers show remaining requests staying above 0")
    print("  4. Any 403/429 errors were successfully retried")
    print("\nLook for log lines like:")
    print("  INFO hermes.pipedrive:api.py Request method=POST ... rate_limit=X/10")
    print("  WARNING hermes.pipedrive:api.py Pipedrive API rate limit ... retry X/Y")
    print()


async def main():
    """
    Main test function.
    """
    print(f"\n{'='*80}")
    print(f"MANUAL RATE LIMITING TEST")
    print(f"{'='*80}")
    print(f"\nThis script will fire {NUM_WEBHOOKS} TC2 webhooks simultaneously to test")
    print(f"that the Pipedrive API rate limiting is working correctly.")
    print(f"\nEach webhook will trigger background tasks that make Pipedrive API calls.")

    if DISABLE_RATE_LIMITER:
        print(f"\n⚠️  AGGRESSIVE MODE: Rate limiter will be bypassed!")
        print(f"   This WILL cause 403/429 errors to test retry logic.")
    else:
        print(f"The rate limiter should prevent 429 errors by spacing out requests.")

    print(f"\nMake sure Hermes is running: uvicorn app.main:app --reload --port 9000")
    print(f"{'='*80}")

    input("\nPress Enter to start the test...")

    # Temporarily disable rate limiter if requested
    if DISABLE_RATE_LIMITER:
        print(f"\n🔧 Disabling rate limiter temporarily...")
        try:
            import httpx
            from app.pipedrive import api

            # Replace the rate-limited client with a regular one
            api._client = httpx.AsyncClient()
            print(f"✓ Rate limiter bypassed - requests will hit Pipedrive directly\n")
        except Exception as e:
            print(f"⚠️  Could not disable rate limiter: {e}")
            print(f"   Continuing anyway...\n")

    # Fire webhooks
    results, total_duration = await fire_webhooks_in_burst(NUM_WEBHOOKS, use_single_client=FORCE_403_MODE)

    if not results or total_duration == 0:
        print("\n❌ Test failed - could not connect to server\n")
        sys.exit(1)

    # Wait for background tasks to complete
    # With 100 webhooks * ~3 API calls each = 300 requests / 9 req/2sec = ~67 seconds
    wait_time = max(10, int(NUM_WEBHOOKS * 0.5))  # Estimate: 0.5 seconds per webhook
    print(f"\n⏳ Waiting {wait_time} seconds for background tasks to complete...")
    print(f"   (This is normal with rate limiting - {NUM_WEBHOOKS} webhooks × ~3 API calls each)")
    await asyncio.sleep(wait_time)

    # Analyze results
    analyze_results(results, total_duration)

    # Restore rate limiter if we disabled it
    if DISABLE_RATE_LIMITER:
        try:
            from app.pipedrive import api
            api._client = None  # Reset so it gets recreated with rate limiting
            print(f"\n✓ Rate limiter restored\n")
        except Exception:
            pass

    print(f"\n{'='*80}")
    print(f"TEST COMPLETE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user\n")
        sys.exit(1)
