#!/bin/bash
set -e

BRANCH="${GITHUB_REF##*/}"

if [[ "$BRANCH" == "dev" ]]; then
  echo "Running EKS ingress setup..."

  aws configure set aws_access_key_id "${AWS_ACCESS_KEY_ID}"
  aws configure set aws_secret_access_key "${AWS_SECRET_ACCESS_KEY}"
  aws configure set region "${AWS_REGION}"

  aws eks update-kubeconfig --region "$AWS_REGION" --name "ai-platform-eks-clstr-01"

  git clone https://x-access-token:${PAT_GITHUB}@github.com/Xebia-Projects/aws-k8s-ingress-configs.git ingress-repo-eks

  if ! kubectl get pods -A | grep -q ingress-nginx; then
    kubectl apply -f ingress-repo-eks/nginx-controller.yaml
  fi

  kubectl apply -f ingress-repo-eks/ingress.yaml

else
  echo "Skipping deployment for branch '$BRANCH'. Azure deployment logic is not included in this script."
  exit 0
fi

