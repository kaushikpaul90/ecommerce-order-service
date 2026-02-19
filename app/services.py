import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
from app.config import settings

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
async def process_payment(item: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{settings.PAYMENT_SERVICE_URL}/pay",
            json={"item": item}
        )
        response.raise_for_status()
        return response.json()
