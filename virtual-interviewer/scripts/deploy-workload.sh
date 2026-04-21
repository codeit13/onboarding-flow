#!/bin/bash
set -e

BRANCH="${GITHUB_REF##*/}"
REPO_NAME=$(basename "$GITHUB_REPOSITORY")
APP_NAME=$(echo "$REPO_NAME" | sed -E 's/.*middleware-//')
echo "App Name: $APP_NAME"

K8S_DIR="k8s"
DEPLOYMENT_FILE="$K8S_DIR/deployment.yaml"
SERVICE_FILE="$K8S_DIR/service.yaml"

if [[ "$BRANCH" == "dev" ]]; then
  echo "Deploying to EKS..."

  aws configure set aws_access_key_id "${AWS_ACCESS_KEY_ID}"
  aws configure set aws_secret_access_key "${AWS_SECRET_ACCESS_KEY}"
  aws configure set region "${AWS_REGION}"

  aws eks update-kubeconfig --region "$AWS_REGION" --name "ai-platform-eks-clstr-01"

  IMAGE_NAME="${ECR_REGISTRY}/xchat/${APP_NAME}:latest"
  NAMESPACE="default"
else
  echo "Skipping deployment for branch '$BRANCH'. Azure deployment logic is not included in this script."
  exit 0
fi

# Restore original YAMLs in case of previous sed substitutions
git restore "$DEPLOYMENT_FILE" || true

# Replace placeholders in the deployment file
sed -i "s|\${APP_NAME}|$APP_NAME|g" "$DEPLOYMENT_FILE"
sed -i "s|\${IMAGE_NAME}|$IMAGE_NAME|g" "$DEPLOYMENT_FILE"
sed -i "s|\${NAMESPACE}|$NAMESPACE|g" "$DEPLOYMENT_FILE"
sed -i "s|\${NAMESPACE}|$NAMESPACE|g" "$SERVICE_FILE"
sed -i "s|\${APP_NAME}|$APP_NAME|g" "$SERVICE_FILE"

echo "Applying $DEPLOYMENT_FILE to namespace: $NAMESPACE"
kubectl apply -n "$NAMESPACE" -f "$DEPLOYMENT_FILE"

echo "Applying $SERVICE_FILE to namespace: $NAMESPACE"
kubectl apply -n "$NAMESPACE" -f "$SERVICE_FILE"

echo "Rolling out deployment/$APP_NAME in namespace $NAMESPACE"
kubectl rollout restart deployment/"$APP_NAME" -n "$NAMESPACE"
