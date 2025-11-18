#!/bin/bash
set -e

# Determine the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Project root: $PROJECT_ROOT"

# Get the account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="ap-southeast-1"

# ECR repository name
ECR_REPOSITORY="thermal-viewer-backend"

# Full repository URI
ECR_REPOSITORY_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"

# Log in to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPOSITORY_URI

echo "Setting up Docker buildx builder..."
# Check if the builder already exists and remove it if it does
if docker buildx ls | grep -q thermal-viewer-builder; then
    echo "Builder already exists, removing it first..."
    docker buildx rm thermal-viewer-builder
fi

# Create a new builder instance
docker buildx create --name thermal-viewer-builder --use

# Check builder info
docker buildx inspect --bootstrap

echo "Building thermal-viewer-backend image for AMD64 platform..."
cd "$PROJECT_ROOT"

# Build and push directly for AMD64 only
docker buildx build \
  --platform=linux/amd64 \
  --no-cache \
  -t $ECR_REPOSITORY_URI:latest \
  --push \
  -f Dockerfile \
  .

echo "Successfully built and pushed Docker image for linux/amd64: $ECR_REPOSITORY_URI:latest"

# Clean up the builder
docker buildx rm thermal-viewer-builder

echo ""
echo "✅ Backend image ready for deployment!"
echo "   Image: $ECR_REPOSITORY_URI:latest"
echo ""
echo "To deploy on EC2:"
echo "   1. SSH to thermal-viewer EC2"
echo "   2. cd /opt/thermal-viewer"
echo "   3. docker-compose pull backend"
echo "   4. docker-compose up -d backend"
