import requests
import time
import logging

logger = logging.getLogger("order-service")

def call_with_retry(url, payload, retries=3, delay=1):
    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=3)

            if response.status_code == 200:
                return response.json()

            logger.warning(f"Non-200 response: {response.status_code}")

        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {str(e)}")

        time.sleep(delay)

    raise Exception("Downstream service unavailable after retries")
