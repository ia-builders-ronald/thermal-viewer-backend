# Thermal Viewer Backend - Future Tasks

This file tracks future enhancements, investigations, and considerations for the Thermal Viewer Backend project.

## Security & Production Readiness

### Restrict CORS Origins
**Priority:** High
**Status:** Pending
**Current State:** CORS allows all origins (`allow_origins=["*"]`)
**Action Needed:**
- Update Flask-CORS configuration to restrict to specific Amplify domain
- After Amplify deployment, get the app URL (e.g., `https://main.xxxxx.amplifyapp.com`)
- Update `app.py` CORS configuration:
  ```python
  CORS(app, origins=[
      "https://main.xxxxx.amplifyapp.com",  # Amplify default domain
      "https://thermal-viewer.yourdomain.com"  # Custom domain (if configured)
  ])
  ```
**Blocked By:** Amplify deployment (need Amplify app URL)
**Related Files:** `app.py` (line 43-49)

---

### Configure HTTPS Hostname for Backend
**Priority:** High
**Status:** Pending
**Current State:** Backend accessible via `http://<ec2-ip>:5001`
**Action Needed:**
- Option 1: Application Load Balancer (ALB) with ACM certificate
- Option 2: CloudFront distribution with ALB origin
- Option 3: Nginx reverse proxy on EC2 with Let's Encrypt
**Recommended:** ALB + ACM for production
**Benefits:**
- HTTPS encryption
- Custom domain (e.g., `api.thermal-viewer.yourdomain.com`)
- Health checks
- Auto-scaling support
**Blocked By:** Domain name decision
**Related Files:** `docker-compose.yml`, `DEPLOYMENT.md`

---

## Deployment & DevOps

### Setup Auto-Deploy from Git to Amplify
**Priority:** Medium
**Status:** Pending
**Current State:** Manual deployment via `amplify publish`
**Action Needed:**
- Create GitHub/GitLab repository for thermal-viewer-frontend
- Connect repository to Amplify Console
- Configure build settings in Amplify
- Enable automatic deployments on push to main branch
**Benefits:**
- Automated CI/CD
- Preview deployments for pull requests
- Rollback capability
**Blocked By:** Phase 3 (frontend creation)
**Related Files:** `thermal-viewer-frontend/amplify.yml` (to be created)

---

### Add Authentication (Cognito)
**Priority:** Medium (Future Phase)
**Status:** Deferred
**Current State:** No authentication - open access
**Action Needed:**
- Create AWS Cognito User Pool
- Update Flask app to validate JWT tokens
- Add authentication middleware
- Update frontend to handle login/logout
- Protect API endpoints
**Blocked By:** User requirements clarification
**Related Files:** `app.py` (new middleware), `services/*.py` (endpoint protection)

---

## Features & Enhancements

### Add Caching Layer
**Priority:** Low
**Status:** Research needed
**Current State:** Every request fetches from S3/DynamoDB
**Action Needed:**
- Evaluate if caching is needed (check latency metrics first)
- Options:
  - ElastiCache (Redis/Memcached)
  - Application-level caching (Flask-Caching)
  - CloudFront for static assets
**Benefits:**
- Reduced latency
- Lower AWS costs
- Better user experience
**Blocked By:** Performance metrics analysis
**Related Files:** `services/*.py`

---

### Add Logging and Monitoring
**Priority:** Medium
**Status:** Pending
**Current State:** Basic console logging
**Action Needed:**
- CloudWatch Logs integration
- Structured logging (JSON format)
- Custom metrics for API usage
- Error tracking (e.g., Sentry)
- Dashboard for monitoring
**Related Files:** `app.py` (logging configuration)

---

## Technical Debt

### Improve Error Handling
**Priority:** Medium
**Status:** Pending
**Current State:** Generic 500 errors returned
**Action Needed:**
- Add custom exception classes
- Return specific HTTP status codes (404, 403, etc.)
- Include error codes in responses
- Add request tracing/correlation IDs
**Related Files:** `app.py`, `services/*.py`

---

### Add API Rate Limiting
**Priority:** Low
**Status:** Pending
**Current State:** No rate limiting
**Action Needed:**
- Implement Flask-Limiter or AWS WAF
- Set per-IP rate limits
- Add API key support for higher limits
**Related Files:** `app.py`

---

### Add API Documentation
**Priority:** Medium
**Status:** Pending
**Current State:** Documentation in README.md only
**Action Needed:**
- Add OpenAPI/Swagger spec
- Use Flask-RESTX or similar for auto-generated docs
- Interactive API explorer at `/docs`
**Related Files:** `app.py`

---

## Performance Optimizations

### Optimize DynamoDB Queries
**Priority:** Low
**Status:** Monitor
**Current State:** Uses scan operations for some queries
**Action Needed:**
- Review query patterns
- Add GSI if needed for efficient queries
- Use pagination for large result sets
**Related Files:** `services/mosaic_service.py`, `services/image_service.py`

---

### Optimize S3 Presigned URL Generation
**Priority:** Low
**Status:** Monitor
**Current State:** Generates presigned URLs on every request
**Action Needed:**
- Cache presigned URLs (1-hour expiration)
- Evaluate if CloudFront distribution would be better
**Related Files:** `services/image_service.py`, `services/mosaic_service.py`

---

## Documentation

### Add Architecture Diagram
**Priority:** Low
**Status:** Pending
**Action Needed:**
- Create system architecture diagram
- Show data flow between components
- Document AWS services used
**Related Files:** `README.md`, `DEPLOYMENT.md`

---

### Add API Versioning Strategy
**Priority:** Low
**Status:** Pending
**Current State:** No API versioning
**Action Needed:**
- Define versioning strategy (URL path vs header)
- Plan backward compatibility approach
**Related Files:** `app.py`

---

## Environment-Specific

### Create Staging Environment
**Priority:** Low
**Status:** Pending
**Current State:** Only development environment exists
**Action Needed:**
- Deploy separate EC2 instance for staging
- Use separate DynamoDB tables (or table prefixes)
- Use separate S3 bucket (or prefixes)
- Configure Amplify staging branch
**Blocked By:** Cost/resource approval

---

*Last Updated: 2025-01-14*
