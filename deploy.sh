#!/bin/bash
set -e

echo "🚀 Starting deployment of Order microservice to Minikube..."

# Load .env file if it exists
if [ -f .env ]; then
  echo "🔧 Loading environment variable(s) from .env"
  export $(grep -v '^#' .env | xargs)
else
  echo "⚠️ .env file not found! Make sure DOCKER_HUB_USERNAME is set."
  exit 1
fi

# Validate DOCKER_HUB_USERNAME
if [ -z "$DOCKER_HUB_USERNAME" ]; then
  echo "❌ DOCKER_HUB_USERNAME is not set. Exiting."
  exit 1
fi

# Start Minikube if not running
if ! minikube status >/dev/null 2>&1; then
  echo "🔧 Starting Minikube..."
  minikube start
else
  echo "✅ Minikube already running."
fi

SERVICE_NAME="order-service"
CHART_DIR="./helm"

# Resolve environment variables in values.yaml
echo "🔄 Resolving Helm values..."
envsubst < "$CHART_DIR/values.yaml" > "$CHART_DIR/values-resolved.yaml"

# Deploy using Helm
echo "📦 Deploying $SERVICE_NAME to Minikube..."
helm upgrade --install "$SERVICE_NAME" "$CHART_DIR" -f "$CHART_DIR/values-resolved.yaml"

# Wait for pods to be ready
echo "⏳ Waiting for pods to be ready..."
kubectl rollout status deployment/$SERVICE_NAME --timeout=15s

# Get service URL
echo "🌐 Service URL:"
minikube service $SERVICE_NAME --url

# echo "📦 Applying Kubernetes manifests..."

# # Apply all manifests
# kubectl apply -f k8s/order-deployment-template.yaml
# kubectl apply -f k8s/order-service-template.yaml

# echo ${DOCKER_HUB_USERNAME}

# echo "⏳ Waiting for all pods to become ready..."
# kubectl wait --for=condition=available --timeout=15s deployment/order-service

# echo "✅ Order service deployed successfully!"

# echo ""
# echo "🌐 Access Order service via the following URL:"

# # Retrieve and print service URL
# echo "Order service: $(minikube service order-service --url)"

echo ""
echo "🎉 Deployment complete!"
