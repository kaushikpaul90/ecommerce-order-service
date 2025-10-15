#!/bin/bash
set -e

echo "🚀 Starting deployment of Order microservice to Minikube..."

# Start Minikube if not running
if ! minikube status >/dev/null 2>&1; then
  echo "🔧 Starting Minikube..."
  minikube start
else
  echo "✅ Minikube already running."
fi

echo "📦 Applying Kubernetes manifests..."

# Apply all manifests
kubectl apply -f k8s/order-deployment-template.yaml
kubectl apply -f k8s/order-service-template.yaml

echo "⏳ Waiting for all pods to become ready..."
kubectl wait --for=condition=available --timeout=120s deployment/order-service

echo "✅ Order service deployed successfully!"

echo ""
echo "🌐 Access Order service via the following URL:"

# Retrieve and print service URL
echo "Order service: $(minikube service order-service --url)"

echo ""
echo "🎉 Deployment complete!"
