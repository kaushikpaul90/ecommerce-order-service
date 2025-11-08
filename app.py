from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import httpx
import uuid
import os
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

app = FastAPI(title="Order Service")

# Config via environment variables
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_URL", "http://192.168.105.2:30002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_URL", "http://192.168.105.2:30003")
SHIPPING_SERVICE_URL = os.getenv("SHIPPING_URL", "http://192.168.105.2:30004")
DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://192.168.105.2:30000")
# INVENTORY_SERVICE_URL = os.getenv("INVENTORY_URL", "http://localhost:8006")
# PAYMENT_SERVICE_URL = os.getenv("PAYMENT_URL", "http://localhost:8005")
# SHIPPING_SERVICE_URL = os.getenv("SHIPPING_URL", "http://localhost:8007")
# DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://localhost:8000")

class Address(BaseModel):
    line1: str
    city: str
    country: str
    postalCode: str

class OrderItem(BaseModel):
    sku: str
    qty: int
    price: float

class CreateOrderRequest(BaseModel):
    userId: Optional[str] = None
    address: Address
    currency: str = "INR"
    items: List[OrderItem]

class Order(BaseModel):
    id: str
    userId: Optional[str]
    address: Address
    currency: str
    items: List[OrderItem]
    status: str  # created | cancelled | completed | pending
    reservationId: Optional[str] = None
    paymentIntentId: Optional[str] = None
    # chargeId: Optional[str] = None
    shipmentId: Optional[str] = None

IDEMPOTENCY: Dict[str, str] = {}  # Idempotency-Key -> orderId

@app.get("/health")
def health():
    return {"status": "ok", "service": "Order Service"}

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

def maybe_retry(func):
    if DEBUG_MODE:
        return func  # No retry
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5),
        retry=retry_if_exception_type(httpx.HTTPError)
    )(func)

# @maybe_retry
# @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5), retry=retry_if_exception_type(httpx.HTTPError))
async def call_service(client: httpx.AsyncClient, method: str, url: str, json: Any = None, headers: dict | None = None):
    resp = await client.request(method, url, json=json, headers=headers, timeout=10.0)
    resp.raise_for_status()
    if resp.content:
        return resp.json()
    return None

@app.post("/orders", response_model=Order, status_code=201)
async def create_order(payload: CreateOrderRequest, x_idempotency_key: Optional[str] = Header(None)):
    # Idempotency check (simple in-memory)
    if x_idempotency_key and x_idempotency_key in IDEMPOTENCY:
        oid = IDEMPOTENCY[x_idempotency_key]
        # fetch from DB
        async with httpx.AsyncClient() as c:
            r = await call_service(c, "GET", f"{DATABASE_SERVICE_URL}/orders/{oid}")
        return r

    oid = str(uuid.uuid4())
    order = {
        "id": oid,
        "userId": payload.userId or "anonymous",
        "address": {
            "line1": payload.address.line1 if payload.address and hasattr(payload.address, "line1") else "",
            "city": payload.address.city if payload.address and hasattr(payload.address, "city") else "",
            "country": getattr(payload.address, "country", "IN") or "IN",
            "postalCode": getattr(payload.address, "postalCode", "") or "",
            "zipcode": getattr(payload.address, "postalCode", "") or "",  # backward compatibility
        },
        "items": [it.dict() for it in payload.items],
        "total": sum(it.qty * it.price for it in payload.items),
        "currency": getattr(payload, "currency", "INR") or "INR",
        "status": "created",
    }

    # persist to database
    async with httpx.AsyncClient() as client:
        await call_service(client, "POST", f"{DATABASE_SERVICE_URL}/orders", json=order)

    if x_idempotency_key:
        IDEMPOTENCY[x_idempotency_key] = oid

    reservation_id = None
    payment_id = None
    shipment_id = None

    # attempt to finalize: reserve inventory, process payment, create shipment
    try:
        async with httpx.AsyncClient() as client:
            # 1) Reserve inventory
            inv_payload = {"orderId": oid, "items": [it.dict() for it in payload.items]}
            try:
                inv_resp = await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reserve", json=inv_payload)
                reservation_id = inv_resp.get("id") if isinstance(inv_resp, dict) else None
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response is not None else 502
                try:
                    upstream_detail = e.response.json().get("detail", e.response.text) if e.response is not None else str(e)
                except Exception:
                    upstream_detail = e.response.text if e.response is not None else str(e)

                # Cancel the order in DB
                order["status"] = "cancelled"
                try:
                    await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)
                except Exception:
                    pass

                if 400 <= status < 500:
                    raise HTTPException(status_code=status, detail=upstream_detail)
                raise HTTPException(status_code=502, detail=f"Upstream error from inventory service: {upstream_detail}")

            # 2) Process payment
            pay_payload = {"id": str(uuid.uuid4()), "order_id": oid, "amount": order["total"], "status": "pending"}
            try:
                pay_resp = await call_service(client, "POST", f"{PAYMENT_SERVICE_URL}/payments", json=pay_payload)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response is not None else 502
                try:
                    upstream_detail = e.response.json().get("detail", e.response.text) if e.response is not None else str(e)
                except Exception:
                    upstream_detail = e.response.text if e.response is not None else str(e)

                # Cancel order and release reservation
                order["status"] = "cancelled"
                try:
                    await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)
                except Exception:
                    pass
                if reservation_id:
                    try:
                        await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reservations/{reservation_id}/release")
                    except Exception:
                        pass

                if 400 <= status < 500:
                    raise HTTPException(status_code=status, detail=upstream_detail)
                raise HTTPException(status_code=502, detail=f"Upstream error from payment service: {upstream_detail}")

            # If payment succeeded, capture payment id and ensure business-success
            if isinstance(pay_resp, dict):
                pstatus = pay_resp.get("status", "").lower()
                payment_id = pay_resp.get("id")
                # a payment response with non-success business state -> treat as failure
                if pstatus not in ("completed", "success"):
                    # cancel and release reservation
                    order["status"] = "cancelled"
                    try:
                        await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)
                    except Exception:
                        pass
                    if reservation_id:
                        try:
                            await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reservations/{reservation_id}/release")
                        except Exception:
                            pass
                    # surface payment failure
                    raise HTTPException(status_code=402, detail=pay_resp.get("detail", f"Payment failed (status={pstatus})"))

            # 3) Create shipment
            ship_payload = {"id": str(uuid.uuid4()), "order_id": oid, "address": payload.address.dict(), "items": [it.dict() for it in payload.items], "status": "created"}
            try:
                ship_resp = await call_service(client, "POST", f"{SHIPPING_SERVICE_URL}/shipments", json=ship_payload)
                shipment_id = ship_resp.get("id") if isinstance(ship_resp, dict) else ship_payload["id"]
            except httpx.HTTPStatusError as e:
                # Shipping returned a client/server error. We must refund and cleanup.
                status = e.response.status_code if e.response is not None else 502
                try:
                    upstream_detail = e.response.json().get("detail", e.response.text) if e.response is not None else str(e)
                except Exception:
                    upstream_detail = e.response.text if e.response is not None else str(e)

                # Attempt refund/void immediately (best-effort)
                refund_success = False
                refund_error = None
                if payment_id:
                    try:
                        # call refund endpoint on Payment service (idempotent)
                        await call_service(client, "POST", f"{PAYMENT_SERVICE_URL}/payments/{payment_id}/refund")
                        refund_success = True
                    except httpx.HTTPStatusError as re:
                        # Upstream payment responded with non-2xx on refund
                        try:
                            refund_error = re.response.json().get("detail", re.response.text)
                        except Exception:
                            refund_error = re.response.text if re.response is not None else str(re)
                    except Exception as re:
                        refund_error = str(re)

                # Mark order cancelled/failed_shipping in DB and record refund attempt info (best-effort)
                order["status"] = "failed_shipping"
                if payment_id:
                    order["paymentIntentId"] = payment_id
                    # for clarity store a flag / message (your DB schema can accept it into address or additional fields)
                    # We'll attempt to store refund outcome in the order JSON as additional keys:
                    order["refund_attempt"] = {"success": refund_success, "error": refund_error}

                try:
                    await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)
                except Exception:
                    pass

                # Release reservation if present (best-effort)
                if reservation_id:
                    try:
                        await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reservations/{reservation_id}/release")
                    except Exception:
                        pass

                # Build a helpful error for caller
                if refund_success:
                    detail = f"Shipping failed: {upstream_detail}. Payment refunded."
                else:
                    detail = f"Shipping failed: {upstream_detail}. Refund attempt failed: {refund_error}. Manual reconciliation required."

                # Return 502 Bad Gateway (or 424 Failed Dependency if you prefer)
                raise HTTPException(status_code=502, detail=detail)

            # 4) All succeeded -> mark order completed and commit reservation
            order["status"] = "completed"
            if reservation_id:
                order["reservationId"] = reservation_id
            if payment_id:
                order["paymentIntentId"] = payment_id
            if shipment_id:
                order["shipmentId"] = shipment_id

            await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)

            if reservation_id:
                try:
                    await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reservations/{reservation_id}/commit")
                except Exception:
                    pass

    except HTTPException:
        # re-raise intentionally thrown HTTPExceptions
        raise
    except Exception as e:
        # fallback behavior
        order["status"] = "cancelled"
        async with httpx.AsyncClient() as client:
            try:
                await call_service(client, "PUT", f"{DATABASE_SERVICE_URL}/orders/{oid}", json=order)
                if reservation_id:
                    try:
                        await call_service(client, "POST", f"{INVENTORY_SERVICE_URL}/reservations/{reservation_id}/release")
                    except Exception:
                        pass
                # best-effort refund if payment created but shipping not attempted / failed earlier
                if payment_id:
                    try:
                        await call_service(client, "POST", f"{PAYMENT_SERVICE_URL}/payments/{payment_id}/refund")
                    except Exception:
                        pass
            except Exception:
                pass
        raise HTTPException(500, detail=f"Finalization failed: {e}")

    return order

@app.get("/orders/{oid}", response_model=Order)
async def get_order(oid: str):
    async with httpx.AsyncClient() as client:
        try:
            r = await call_service(client, "GET", f"{DATABASE_SERVICE_URL}/orders/{oid}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(404, detail="Order not found")
            raise
    return r
