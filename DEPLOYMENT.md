# Thermal Viewer Deployment Guide

## Architecture Overview

- **Backend**: Flask API deployed on EC2 via Docker
- **Frontend**: React SPA deployed on AWS Amplify
- **Data**: DynamoDB + S3 (shared with thermal-api)

## Prerequisites

- ✅ ECR repository created: `thermal-viewer-backend`
- ✅ thermal-api rebuilt with MosaicBuilder viewer file uploads
- ✅ Mosaic builds completed with viewer files uploaded to S3
- AWS CLI configured with credentials
- Docker with buildx support
- Amplify CLI installed (`npm install -g @aws-amplify/cli`)

---

## Part 1: Backend Deployment (EC2)

### Step 1: Build and Push Backend Image

From the `thermal-viewer-backend` directory:

```bash
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-backend
./scripts/build_and_push_backend.sh
```

This script will:
- Auto-detect your AWS account ID
- Login to ECR
- Build the backend Docker image for AMD64 (EC2 compatible)
- Push to ECR: `{account}.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend:latest`

**Expected output**:
```
✅ Backend image ready for deployment!
   Image: 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com/thermal-viewer-backend:latest
```

### Step 2: Launch EC2 Instance

#### Instance Configuration

- **Type**: `t3.medium` (2 vCPU, 4GB RAM)
- **AMI**: Amazon Linux 2
- **Storage**: 30GB GP3
- **Security Group**:
  - Port 22 (SSH) - Your IP
  - Port 5001 (Backend API) - Anywhere (or restrict to ALB if using one)
- **IAM Role**: Same as thermal-api EC2 (or create new with same permissions)

#### Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-images-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-jobs-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-pads-*",
        "arn:aws:dynamodb:*:*:table/thermal-api-dev-*/index/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::thermal-api-dev-storage-*/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 3: Setup EC2 Instance

SSH to the new instance:

```bash
ssh -i your-key.pem ec2-user@<ec2-ip-address>
```

#### Install Docker

```bash
# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker
sudo service docker start
sudo usermod -a -G docker ec2-user

# Logout and login again for group changes
exit
# SSH back in
```

#### Install Docker Compose

```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify
docker-compose --version
```

#### Create Project Directory

```bash
sudo mkdir -p /opt/thermal-viewer
sudo chown ec2-user:ec2-user /opt/thermal-viewer
cd /opt/thermal-viewer
```

### Step 4: Deploy Backend

#### Copy docker-compose.yml

From your local machine:

```bash
scp -i your-key.pem /Users/ronaldm/Code/tf-workspace/thermal-viewer-backend/docker-compose.yml ec2-user@<ec2-ip-address>:/opt/thermal-viewer/
```

Or create manually on EC2 (content from `thermal-viewer-backend/docker-compose.yml`)

#### Login to ECR and Start Service

```bash
# Login to ECR
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com

# Pull and start
cd /opt/thermal-viewer
docker-compose pull
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

#### Verify Backend

```bash
# Health check
curl http://localhost:5001/health

# Test API
curl http://localhost:5001/api/sites
```

### Step 5: (Optional) Setup HTTPS with ALB

For production, configure Application Load Balancer:

1. Create ALB in AWS Console
2. Add target group pointing to EC2:5001
3. Configure ACM certificate for HTTPS
4. Update DNS to point to ALB
5. Update CORS in `app.py` to allow ALB domain

---

## Part 2: Frontend Deployment (Amplify)

### Step 1: Install Amplify CLI

```bash
npm install -g @aws-amplify/cli
amplify configure
```

### Step 2: Initialize Amplify in Frontend Project

From `thermal-viewer-frontend` directory (after Phase 3):

```bash
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-frontend

# Initialize Amplify
amplify init

# Follow prompts:
# - Project name: thermal-viewer-frontend
# - Environment: dev
# - Editor: VS Code (or your choice)
# - App type: javascript
# - Framework: react
# - Source directory: src
# - Distribution directory: dist
# - Build command: npm run build
# - Start command: npm run dev
```

### Step 3: Configure Environment Variables

In Amplify Console (after first deployment):

1. Go to AWS Amplify Console
2. Select your app
3. Click "Environment variables"
4. Add:
   - Key: `VITE_API_BASE_URL`
   - Value: `https://your-backend-hostname` or `http://<ec2-ip>:5001` (temporary)

### Step 4: Manual Deployment

```bash
# Build and deploy
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-frontend
amplify publish
```

This will:
- Build the React app (`npm run build`)
- Upload to Amplify hosting
- Provide a URL (e.g., `https://dev.xxxxx.amplifyapp.com`)

### Step 5: Setup Auto-Deploy (Future)

1. Push frontend code to GitHub/GitLab
2. In Amplify Console, connect repository
3. Configure build settings (use `amplify.yml`)
4. Enable auto-deploy on push to main branch

---

## Updating Deployments

### Update Backend

```bash
# Local machine - rebuild and push
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-backend
./scripts/build_and_push_backend.sh

# EC2 - pull and restart
ssh ec2-user@<ec2-ip>
cd /opt/thermal-viewer
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 058264237306.dkr.ecr.ap-southeast-1.amazonaws.com
docker-compose pull
docker-compose up -d
```

### Update Frontend

**Manual**:
```bash
cd /Users/ronaldm/Code/tf-workspace/thermal-viewer-frontend
amplify publish
```

**Auto (after Git connection)**:
```bash
git add .
git commit -m "Update frontend"
git push origin main
# Amplify auto-deploys
```

---

## Monitoring and Maintenance

### View Backend Logs

```bash
# SSH to EC2
cd /opt/thermal-viewer
docker-compose logs -f backend
```

### View Frontend Logs

Check Amplify Console → Your App → Deployments → Build logs

### Restart Services

**Backend**:
```bash
cd /opt/thermal-viewer
docker-compose restart
```

**Frontend**:
Redeploy via Amplify Console or `amplify publish`

---

## Troubleshooting

### Backend: Can't Access API from Browser

1. Check EC2 security group allows port 5001
2. Verify backend is running: `docker-compose ps`
3. Check logs: `docker-compose logs backend`

### Frontend: API Calls Failing

1. Check CORS configuration in backend `app.py`
2. Verify `VITE_API_BASE_URL` in Amplify environment variables
3. Check browser console for CORS errors

### Frontend: Build Fails in Amplify

1. Check build logs in Amplify Console
2. Verify `amplify.yml` build specification
3. Check environment variables are set

---

## Production Checklist

- [ ] Backend behind ALB with HTTPS
- [ ] Update CORS to restrict to Amplify domain (see `TODO.md`)
- [ ] Custom domain for frontend (via Amplify)
- [ ] Custom domain for backend (via Route 53 → ALB)
- [ ] CloudWatch alarms for backend
- [ ] CloudWatch alarms for frontend (via Amplify)
- [ ] Auto-deploy enabled for frontend
- [ ] Backup strategy for EC2
- [ ] Cost monitoring setup

---

## Quick Reference

### Backend Deployment

```bash
# Build and push
cd thermal-viewer-backend
./scripts/build_and_push_backend.sh

# Deploy on EC2
ssh ec2-user@<ec2-ip>
cd /opt/thermal-viewer
docker-compose pull && docker-compose up -d
```

### Frontend Deployment

```bash
# Manual
cd thermal-viewer-frontend
amplify publish

# Auto (after Git setup)
git push origin main
```

### Service URLs

- **Backend API**: `http://<ec2-ip>:5001` (dev) or `https://api.yourdomain.com` (prod)
- **Frontend**: `https://dev.xxxxx.amplifyapp.com` (dev) or `https://thermal-viewer.yourdomain.com` (prod)
- **Backend Health**: `http://<ec2-ip>:5001/health`
