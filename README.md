# Order Service

A microservice component of an e-commerce platform that handles order management, integrating with inventory, payment, and shipping services. Built with FastAPI and designed for Kubernetes deployment.

## Features

- **Order Management**: Create and retrieve orders
- **Service Integration**: Coordinates with inventory, payment, and shipping services
- **Idempotency**: Supports idempotent order creation via headers
- **Kubernetes Ready**: Includes Helm charts for deployment
- **Auto-scaling**: HPA configuration for dynamic scaling
- **Docker Support**: Multi-arch container images (amd64/arm64)

## Prerequisites

- Python 3.11+
- Docker
- Kubernetes cluster (e.g., Minikube)
- Helm 3.x

## Local Development

1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure environment variables (optional, defaults provided):
```bash
export INVENTORY_URL="http://localhost:8006"
export PAYMENT_URL="http://localhost:8005"
export SHIPPING_URL="http://localhost:8007"
export DATABASE_SERVICE_URL="http://localhost:8000"
export DEBUG_MODE="true"  # Disables retries for easier debugging
```

3. Run the service:
```bash
uvicorn app:app --host 0.0.0.0 --port 8004 --reload
```

## API Endpoints

### Health Check
```
GET /health
Response: {"status": "ok", "service": "Order Service"}
```

### Create Order
```
POST /orders
Header: X-Idempotency-Key (optional)

Request Body:
{
    "userId": "string" (optional),
    "address": {
        "line1": "string",
        "city": "string",
        "country": "string",
        "postalCode": "string"
    },
    "currency": "INR" (default),
    "items": [
        {
            "sku": "string",
            "qty": int,
            "price": float
        }
    ]
}
```

### Get Order
```
GET /orders/{orderId}
Response: Order details including status and related IDs
```

## Deployment

### Docker Build

Build the image locally:
```bash
docker build -t your-registry/order-service:latest .
```

### Kubernetes Deployment (using Helm)

1. Set up environment:
```bash
export DOCKER_HUB_USERNAME="your-username"
```

2. Deploy using the provided script:
```bash
chmod +x deploy.sh
./deploy.sh
```

Or manually using Helm:
```bash
helm upgrade --install order-service helm_chart -f helm_chart/values.yaml
```

### Helm Configuration

Key configurations in `values.yaml`:
```yaml
replicaCount: 1

image:
  repository: "${DOCKER_HUB_USERNAME}/order-service"
  tag: latest
  pullPolicy: Always

service:
  type: NodePort
  port: 8080
  nodePort: 30001

containerPort: 8004

hpa:
  enabled: true
  minReplicas: 1
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

## Architecture

The Order Service orchestrates the order creation process through several steps:

1. **Order Creation**
   - Validates the order request
   - Creates initial order record
   - Handles idempotency

2. **Inventory Management**
   - Reserves inventory items
   - Commits/releases reservations based on order outcome

3. **Payment Processing**
   - Initiates payment authorization
   - Handles refunds if subsequent steps fail

4. **Shipment Creation**
   - Creates shipment records
   - Rolls back previous steps if shipping fails

## Error Handling

The service implements comprehensive error handling:
- Automatic retries for transient failures
- Compensating transactions for partial failures
- Detailed error responses with upstream service information
- Idempotency protection for retry safety

## Development Guidelines

1. **Environment Variables**
   - Use `.env` file for local development
   - All service URLs configurable via environment
   - Debug mode toggle available

2. **Testing**
   - Run with `DEBUG_MODE=true` for local testing
   - Use provided health endpoint for monitoring

3. **Deployment**
   - CI workflow provided for Docker Hub publishing
   - Helm charts handle Kubernetes deployment
   - HPA configured for auto-scaling

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is part of a learning assignment. Please check with the repository owner for usage permissions.
