from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import time
import logging
import uuid

from app.config import settings
from app.logging_config import configure_logging
from app.database import Base, engine, SessionLocal
from app.models import Order
from app.schemas import OrderRequest
from app.services import process_payment
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT
from app.health import router as health_router
from app.failure_injection import apply_failure
from app.utils import call_with_retry

configure_logging()
logger = logging.getLogger(settings.SERVICE_NAME)

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(health_router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    correlation_id = str(uuid.uuid4())

    try:
        response = await call_next(request)

        REQUEST_COUNT.labels(
            service=settings.SERVICE_NAME,
            endpoint=request.url.path
        ).inc()

        REQUEST_LATENCY.labels(
            service=settings.SERVICE_NAME,
            endpoint=request.url.path
        ).observe(time.time() - start_time)

        response.headers["X-Correlation-ID"] = correlation_id
        return response

    except Exception:
        ERROR_COUNT.labels(
            service=settings.SERVICE_NAME,
            endpoint=request.url.path
        ).inc()
        logger.error("Unhandled exception", exc_info=True)
        raise


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/order")
async def create_order(order: OrderRequest, db: Session = Depends(get_db)):
    apply_failure(settings.FAILURE_MODE)

    item = order.item
    quantity = order.quantity

    if not item:
        raise HTTPException(status_code=400, detail="Item is required")

    # STEP 0: Persist initial order
    new_order = Order(item=item, quantity=quantity, status="CREATED")
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    logger.info("Order created", extra={"order_id": new_order.id})

    # STEP 1: PAYMENT
    try:
        # Example static price (can later move to DB/config)
        UNIT_PRICE = 100  

        total_amount = UNIT_PRICE * quantity

        call_with_retry(
            f"{settings.PAYMENT_SERVICE_URL}/pay",
            {
                "item": item,
                "quantity": quantity,
                "amount": total_amount
            }
        )

        new_order.status = "PAYMENT_SUCCESS"
        db.commit()

        logger.info("Payment successful",
                    extra={
                        "order_id": new_order.id,
                        "amount": total_amount
                    })
    except Exception as e:
        new_order.status = "FAILED_PAYMENT"
        db.commit()

        logger.error("Payment failed",
                     extra={"order_id": new_order.id, "error": str(e)})

        return {
            "status": "payment_failed",
            "order_id": new_order.id
        }

    # STEP 2: INVENTORY
    try:
        inventory_response = call_with_retry(
            f"{settings.INVENTORY_SERVICE_URL}/reserve",
            {"item_name": item, "quantity": quantity}
        )

        if inventory_response.get("status") != "reserved":
            new_order.status = "FAILED_INVENTORY"
            db.commit()

            return {
                "status": "inventory_failed",
                "order_id": new_order.id
            }

        new_order.status = "INVENTORY_RESERVED"
        db.commit()

        logger.info("Inventory reserved",
                    extra={"order_id": new_order.id})

    except Exception as e:
        new_order.status = "FAILED_INVENTORY"
        db.commit()

        logger.error("Inventory service unavailable",
                     extra={"order_id": new_order.id, "error": str(e)})

        return {
            "status": "inventory_unavailable",
            "order_id": new_order.id
        }

    # STEP 3: SHIPPING
    try:
        shipping_response = call_with_retry(
            f"{settings.SHIPPING_SERVICE_URL}/ship",
            {"item_name": item, "quantity": quantity}
        )

        if shipping_response.get("status") != "shipped":
            new_order.status = "FAILED_SHIPPING"
            db.commit()

            return {
                "status": "shipping_failed",
                "order_id": new_order.id
            }

        new_order.status = "SHIPPED"
        db.commit()

        logger.info("Shipping successful",
                    extra={"order_id": new_order.id})

    except Exception as e:
        new_order.status = "FAILED_SHIPPING"
        db.commit()

        logger.error("Shipping service unavailable",
                     extra={"order_id": new_order.id, "error": str(e)})

        return {
            "status": "shipping_unavailable",
            "order_id": new_order.id
        }

    # FINAL STATE
    new_order.status = "COMPLETED"
    db.commit()

    logger.info("Order completed",
                extra={"order_id": new_order.id})

    return {
        "status": "order_completed",
        "order_id": new_order.id
    }
