import os

class Settings:
    SERVICE_NAME = os.getenv("SERVICE_NAME", "order-service")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    FAILURE_MODE = os.getenv("FAILURE_MODE", "NONE")

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5433")
    DB_NAME = os.getenv("DB_NAME", "orders")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

    PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8005")
    INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8006")
    SHIPPING_SERVICE_URL = os.getenv("SHIPPING_SERVICE_URL", "http://localhost:8007")

settings = Settings()
