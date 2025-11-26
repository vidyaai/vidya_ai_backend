# Google Forms Integration - Server Deployment Guide

## Production Server Credentials Setup

For deploying on a server, you have multiple secure options for Google Cloud credentials:

### Method 1: Environment Variable (Recommended for Production)

Set the entire service account JSON as an environment variable:

```bash
# On your server, set this environment variable:
export GOOGLE_CLOUD_CREDENTIALS_JSON='{"type": "service_account", "project_id": "your-project", "private_key_id": "...", "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n", "client_email": "...", "client_id": "...", "auth_uri": "...", "token_uri": "...", "auth_provider_x509_cert_url": "...", "client_x509_cert_url": "..."}'
```

### Method 2: Service Account File Path (Alternative)

Place the service account file on your server and set the path:

```bash
# Place your vidyaai-forms-integrations-0270b6b160e0.json file securely on server
export GOOGLE_CLOUD_CREDENTIALS_FILE="/secure/path/to/vidyaai-forms-integrations-0270b6b160e0.json"
```

### Method 3: Google Cloud Platform (If running on GCP)

If your server is running on Google Cloud Platform, use Application Default Credentials (no manual setup required).

## Docker Deployment

If using Docker, pass credentials as environment variables:

```dockerfile
# In your Dockerfile or docker-compose.yml
ENV GOOGLE_CLOUD_CREDENTIALS_JSON=${GOOGLE_CLOUD_CREDENTIALS_JSON}
```

```yaml
# docker-compose.yml
services:
  vidya-backend:
    environment:
      - GOOGLE_CLOUD_CREDENTIALS_JSON=${GOOGLE_CLOUD_CREDENTIALS_JSON}
```

## Security Best Practices

1. **Never commit credentials to Git** - Use environment variables
2. **Use service accounts** - Not personal Google accounts  
3. **Minimal permissions** - Only Forms API access needed
4. **Rotate keys regularly** - Generate new service account keys periodically
5. **Monitor usage** - Check Google Cloud Console for API usage

## Required Google Cloud Setup

1. **Enable Google Forms API** in Google Cloud Console
2. **Create Service Account** with Forms API permissions
3. **Download service account key** (JSON format)
4. **Set environment variable** on your server

## Environment Variables Summary

```bash
# Required for Google Forms (choose ONE method):
GOOGLE_CLOUD_CREDENTIALS_JSON="{...complete JSON...}"
# OR
GOOGLE_CLOUD_CREDENTIALS_FILE="/path/to/service-account.json"

# Your existing environment variables:
DATABASE_URL=postgresql://...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# ... other vars
```

## Testing Deployment

Test if credentials are working on your server:

```bash
# Check if service can initialize
curl -X GET "https://your-server.com/api/health"

# Test Google Forms creation
curl -X POST "https://your-server.com/api/assignments/{id}/generate-google-form" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

The service will automatically detect and use the available credential method in this order:
1. GOOGLE_CLOUD_CREDENTIALS_JSON environment variable  
2. GOOGLE_CLOUD_CREDENTIALS_FILE file path
3. Local development files (for development only)
4. Application Default Credentials (for GCP deployment)