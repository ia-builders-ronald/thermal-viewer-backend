# Cognito CloudFormation Template

This directory contains CloudFormation templates for deploying authentication infrastructure.

## cognito.yaml

Creates a Cognito User Pool and App Client for the Thermal Viewer / Line Loss Analytics application.

### Features

- Email-based sign-in (no username)
- Admin-only user creation (no self-registration)
- Password policy: 8+ chars, uppercase, lowercase, number, symbol
- No client secret (required for browser/SPA apps)
- 1 hour access/ID token validity
- 30 day refresh token validity

### Deployment

```bash
# Deploy to default region
aws cloudformation deploy \
  --template-file cognito.yaml \
  --stack-name thermal-viewer-cognito-dev \
  --parameter-overrides Environment=dev AppName=thermal-viewer

# Deploy to specific region
aws cloudformation deploy \
  --template-file cognito.yaml \
  --stack-name thermal-viewer-cognito-dev \
  --parameter-overrides Environment=dev AppName=thermal-viewer \
  --region ap-southeast-1

# For EDC/LLA deployment
aws cloudformation deploy \
  --template-file cognito.yaml \
  --stack-name lla-cognito-prod \
  --parameter-overrides Environment=prod AppName=line-loss-analytics \
  --region ap-southeast-1 \
  --profile energy
```

### Get Outputs

After deployment, get the User Pool ID and App Client ID:

```bash
aws cloudformation describe-stacks \
  --stack-name thermal-viewer-cognito-dev \
  --query 'Stacks[0].Outputs' \
  --output table
```

### Configure Application

Add the outputs to your environment configuration:

**Frontend (.env.production):**
```
VITE_COGNITO_USER_POOL_ID=ap-southeast-1_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=1234567890abcdefghijk
```

**Backend (docker-compose.yml):**
```yaml
environment:
  - COGNITO_REGION=ap-southeast-1
  - COGNITO_USER_POOL_ID=ap-southeast-1_XXXXXXXXX
```

---

## User Management

### Create a User (AWS Console)

1. Go to AWS Console → Cognito → User Pools → Select your pool
2. Click "Create user"
3. Enter email address
4. Set a temporary password
5. Click "Create user"

The user will be in "Force change password" status.

### Set Permanent Password (CLI)

To bypass the "Force change password" requirement, use the AWS CLI:

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com \
  --password "SecurePassword123!" \
  --permanent
```

**Note:** Replace:
- `ap-southeast-1_XXXXXXXXX` with your User Pool ID
- `user@example.com` with the user's email
- `SecurePassword123!` with the desired password (must meet policy requirements)

### Create User with Permanent Password (One Command)

Combine user creation and password setting:

```bash
# Create user (suppress welcome email)
aws cognito-idp admin-create-user \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS

# Set permanent password
aws cognito-idp admin-set-user-password \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com \
  --password "SecurePassword123!" \
  --permanent
```

### List Users

```bash
aws cognito-idp list-users \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --output table
```

### Delete User

```bash
aws cognito-idp admin-delete-user \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com
```

### Disable/Enable User

```bash
# Disable
aws cognito-idp admin-disable-user \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com

# Enable
aws cognito-idp admin-enable-user \
  --user-pool-id ap-southeast-1_XXXXXXXXX \
  --username user@example.com
```

---

## Delete Stack

To remove the Cognito User Pool and all users:

```bash
aws cloudformation delete-stack --stack-name thermal-viewer-cognito-dev
```

**Warning:** This will delete all users in the pool. This action cannot be undone.
