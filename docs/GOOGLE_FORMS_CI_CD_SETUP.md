# Google Forms Integration CI/CD Setup

## Overview

The Google Forms integration is designed to work seamlessly with the existing CI/CD pipeline that deploys to EC2. This document explains how to configure the necessary credentials and environment variables.

## Required GitHub Secrets

Add the following secrets to your GitHub repository settings:

### Google Cloud Credentials

1. **GOOGLE_CLOUD_CREDENTIALS_JSON**: The complete JSON content of your Google Cloud service account key file
   - Go to Google Cloud Console → IAM & Admin → Service Accounts
   - Create or select your service account (vidyaai-forms-integrations)
   - Create a new key (JSON format)
   - Copy the entire JSON content to this secret

Example structure:
```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "service-account@project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

## CI/CD Workflow Updates

The CI/CD workflow needs to be updated to include the Google Forms credentials. Add these lines to the `.env` file creation section:

```yaml
echo "GOOGLE_CLOUD_CREDENTIALS_JSON=${{ secrets.GOOGLE_CLOUD_CREDENTIALS_JSON }}" >> ./.env
```

## Google Cloud Service Account Permissions

Ensure your service account has the following permissions:
- Google Forms API access
- Forms creation and editing permissions

## Testing

### Local Development
- Place your credentials file as `vidyaai-forms-integrations-0270b6b160e0.json` in the backend root
- Or set `GOOGLE_CLOUD_CREDENTIALS_FILE` environment variable

### Production
- Credentials are automatically loaded from `GOOGLE_CLOUD_CREDENTIALS_JSON` environment variable
- No file storage required on the server

## Assignment Logging Integration

The system includes comprehensive assignment logging that captures:
- Complete question data including mathematical equations
- Assignment metadata (title, description, difficulty)
- Generated Google Forms URLs
- Timestamps for debugging

Logs are stored in `assignment_logs/` directory for developer review.

## Security Notes

1. **Never commit credential files** - they are properly excluded via .gitignore
2. **Use environment variables in production** - credentials are injected during deployment
3. **Rotate credentials regularly** - update GitHub secrets when rotating service account keys
4. **Monitor API usage** - Google Forms API has quotas and limits

## Troubleshooting

### Common Issues

1. **"Google Forms service not available"**
   - Check if `GOOGLE_CLOUD_CREDENTIALS_JSON` secret is set
   - Verify JSON format is valid
   - Ensure service account has correct permissions

2. **"Forms API quota exceeded"**
   - Check Google Cloud Console for quota limits
   - Consider implementing rate limiting

3. **Assignment logging not working**
   - Check write permissions to `assignment_logs/` directory
   - Verify disk space on server

### Debug Commands

```bash
# Check if credentials are loaded
python -c "from src.utils.google_forms_service import GoogleFormsService; print(GoogleFormsService().is_available())"

# Test assignment logging
python -c "from src.utils.assignment_logger import log_published_assignment; print('Logging available')"
```