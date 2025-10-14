
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional, Dict
import httpx
import uuid
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

app = FastAPI(title="Order Service")

# Config (could be env-driven)
# INVENTORY_URL = "http://inventory_service:8006"
# PAYMENT_URL = "http://payment_service:8005"
# SHIPPING_URL = "http://shipping_service:8007"
INVENTORY_URL = "http://localhost:8006"
PAYMENT_URL = "http://localhost:8005"
SHIPPING_URL = "http://localhost:8007"

class Address(BaseModel):
    line1: str
    city: str
    country: str
    postalCode: str

class OrderItem(BaseModel):
    sku: str
    qty: int
    price: float

class Order(BaseModel):
    id: str
    userId: Optional[str]
    address: Address
    currency: str
    items: List[OrderItem]
    status: str  # created | cancelled | completed | pending
    reservationId: Optional[str] = None
    paymentIntentId: Optional[str] = None
    chargeId: Optional[str] = None
    shipmentId: Optional[str] = None

ORDERS: Dict[str, Order] = {}
IDEMPOTENCY: Dict[str, str] = {}  # Idempotency-Key -> orderId

@app.get("/health")
def health():
    return {"status": "ok", "service": "Order Service"}

# @retry(reraise=True, stop=stop_after_attempt(1), wait=wait_exponential(multiplier=0.2, min=0.2, max=2), retry=retry_if_exception_type(httpx.RequestError))
async def post_json(client: httpx.AsyncClient, url: str, json_payload: dict, headers: dict | None = None):
    r = await client.post(url, json=json_payload, headers=headers, timeout=5.0)
    r.raise_for_status()
    return r.json()

# @retry(reraise=True, stop=stop_after_attempt(1), wait=wait_exponential(multiplier=0.2, min=0.2, max=2), retry=retry_if_exception_type(httpx.RequestError))
async def post_nojson(client: httpx.AsyncClient, url: str, headers: dict | None = None):
    r = await client.post(url, headers=headers, timeout=5.0)
    r.raise_for_status()
    return r.json() if r.content else {}

class CreateOrderRequest(BaseModel):
    userId: Optional[str] = None
    address: Address
    currency: str = "INR"
    items: List[OrderItem]

@app.post("/orders", response_model=Order)
async def create_order(payload: CreateOrderRequest, Idempotency_Key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    # Idempotency: if seen before, return existing order
    if Idempotency_Key and Idempotency_Key in IDEMPOTENCY:
        oid = IDEMPOTENCY[Idempotency_Key]
        return ORDERS[oid]

    oid = str(uuid.uuid4())
    order = Order(id=oid, userId=payload.userId, address=payload.address, currency=payload.currency, items=payload.items, status="created")
    ORDERS[oid] = order
    if Idempotency_Key:
        IDEMPOTENCY[Idempotency_Key] = oid

    async with httpx.AsyncClient() as client:
        # Step 1: Reserve Inventory
        try:
            resv = await post_json(client, f"{INVENTORY_URL}/reserve", {"orderId": oid, "items": [it.model_dump() for it in order.items]})
            order.reservationId = resv["id"]
        except httpx.HTTPStatusError as e:
            # Extract detail from response
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            order.status = "cancelled"
            ORDERS[oid] = order
            raise HTTPException(409, detail=f"Inventory reservation failed: {detail}")
        except Exception as e:
            order.status = "cancelled"
            ORDERS[oid] = order
            raise HTTPException(409, detail=f"Inventory reservation failed: {str(e)}")

        # Step 2: Authorize Payment
        grand_total = sum([it.qty * it.price for it in order.items])
        try:
            intent = await post_json(client, f"{PAYMENT_URL}/intents", {"orderId": oid, "amount": grand_total, "currency": order.currency}, headers={"Idempotency-Key": f"order:{oid}:intent"})
            order.paymentIntentId = intent["id"]
            intent = await post_nojson(client, f"{PAYMENT_URL}/intents/{order.paymentIntentId}/confirm")
        except Exception as e:
            # Compensate reservation
            if order.reservationId:
                try:
                    await post_nojson(client, f"{INVENTORY_URL}/reservations/{order.reservationId}/release")
                except Exception:
                    pass
            order.status = "cancelled"
            ORDERS[oid] = order
            raise HTTPException(402, detail=f"Payment authorization failed: {e}")

        # Step 3: Create Shipment
        try:
            shp = await post_json(client, f"{SHIPPING_URL}/shipments", {"orderId": oid, "address": order.address.model_dump(), "items": [it.model_dump() for it in order.items]})
            order.shipmentId = shp["id"]
        except Exception as e:
            # Compensate: void payment (simulate refund path) + release inventory
            if order.paymentIntentId:
                # nothing to void in this demo, but keep placeholder
                pass
            if order.reservationId:
                try:
                    await post_nojson(client, f"{INVENTORY_URL}/reservations/{order.reservationId}/release")
                except Exception:
                    pass
            order.status = "cancelled"
            ORDERS[oid] = order
            raise HTTPException(409, detail=f"Shipping creation failed: {e}")

        # Step 4: Commit Inventory & Capture Payment
        try:
            await post_nojson(client, f"{INVENTORY_URL}/reservations/{order.reservationId}/commit")
            charge = await post_nojson(client, f"{PAYMENT_URL}/intents/{order.paymentIntentId}/capture")
            order.chargeId = charge.get("id")
        except Exception as e:
            # Compensate: refund and release inventory (best effort)
            try:
                if order.chargeId:
                    await post_nojson(client, f"{PAYMENT_URL}/charges/{order.chargeId}/refund")
            except Exception:
                pass
            try:
                await post_nojson(client, f"{INVENTORY_URL}/reservations/{order.reservationId}/release")
            except Exception:
                pass
            order.status = "cancelled"
            ORDERS[oid] = order
            raise HTTPException(500, detail=f"Finalization failed: {e}")

    order.status = "completed"
    ORDERS[oid] = order
    return order

@app.get("/orders/{oid}", response_model=Order)
def get_order(oid: str):
    o = ORDERS.get(oid)
    if not o:
        raise HTTPException(404, detail="Order not found")
    return o
