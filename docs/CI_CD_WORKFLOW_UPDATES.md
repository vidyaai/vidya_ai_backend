# Updated CI/CD Workflow for Google Forms Integration

## Add to .github/workflows/ci-cd.yml

Insert this line in both the local `.env` creation section and the SSH deployment section:

```yaml
echo "GOOGLE_CLOUD_CREDENTIALS_JSON=${{ secrets.GOOGLE_CLOUD_CREDENTIALS_JSON }}" >> ./.env
```

## Complete Updated Sections

### Local .env Creation (around line 44)
```yaml
- name: Create .env file
  run: |
    echo "DATABASE_URL=${{ secrets.DATABASE_URL }}" >> ./.env
    echo "OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}" >> ./.env
    echo "AWS_S3_BUCKET=${{ secrets.AWS_S3_BUCKET }}" >> ./.env
    echo "AWS_S3_REGION=${{ secrets.AWS_S3_REGION }}" >> ./.env
    echo "AWS_ACCESS_KEY_ID=${{ secrets.AWS_ACCESS_KEY_ID }}" >> ./.env
    echo "AWS_SECRET_ACCESS_KEY=${{ secrets.AWS_SECRET_ACCESS_KEY }}" >> ./.env
    echo "FIREBASE_CONFIG=${{ secrets.FIREBASE_CONFIG }}" >> ./.env
    echo "DEEPGRAM_API_KEY=${{ secrets.DEEPGRAM_API_KEY }}" >> ./.env
    echo "STRIPE_SECRET_KEY=${{ secrets.STRIPE_SECRET_KEY }}" >> ./.env
    echo "STRIPE_PUBLISHABLE_KEY=${{ secrets.STRIPE_PUBLISHABLE_KEY }}" >> ./.env
    echo "STRIPE_PLUS_MONTHLY_PRICE_ID=${{ secrets.STRIPE_PLUS_MONTHLY_PRICE_ID }}" >> ./.env
    echo "STRIPE_PLUS_ANNUAL_PRICE_ID=${{ secrets.STRIPE_PLUS_ANNUAL_PRICE_ID }}" >> ./.env
    echo "STRIPE_PRO_MONTHLY_PRICE_ID=${{ secrets.STRIPE_PRO_MONTHLY_PRICE_ID }}" >> ./.env
    echo "STRIPE_PRO_ANNUAL_PRICE_ID=${{ secrets.STRIPE_PRO_ANNUAL_PRICE_ID }}" >> ./.env
    echo "STRIPE_WEBHOOK_SECRET=${{ secrets.STRIPE_WEBHOOK_SECRET }}" >> ./.env
    echo "FRONTEND_URL=${{ secrets.FRONTEND_URL }}" >> ./.env
    echo "GOOGLE_CLOUD_CREDENTIALS_JSON=${{ secrets.GOOGLE_CLOUD_CREDENTIALS_JSON }}" >> ./.env
    echo "POPPLER_PATH=/usr/bin/" >> ./.env
```

### SSH Deployment .env Creation (around line 90)
```yaml
touch .env
cat <<EOF >.env
DATABASE_URL=${{ secrets.DATABASE_URL }}
OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
AWS_S3_BUCKET=${{ secrets.AWS_S3_BUCKET }}
AWS_S3_REGION=${{ secrets.AWS_S3_REGION }}
AWS_ACCESS_KEY_ID=${{ secrets.AWS_ACCESS_KEY_ID }}
AWS_SECRET_ACCESS_KEY=${{ secrets.AWS_SECRET_ACCESS_KEY }}
FIREBASE_CONFIG=${{ secrets.FIREBASE_CONFIG }}
DEEPGRAM_API_KEY=${{ secrets.DEEPGRAM_API_KEY }}
STRIPE_SECRET_KEY=${{ secrets.STRIPE_SECRET_KEY }}
STRIPE_PUBLISHABLE_KEY=${{ secrets.STRIPE_PUBLISHABLE_KEY }}
STRIPE_PLUS_MONTHLY_PRICE_ID=${{ secrets.STRIPE_PLUS_MONTHLY_PRICE_ID }}
STRIPE_PLUS_ANNUAL_PRICE_ID=${{ secrets.STRIPE_PLUS_ANNUAL_PRICE_ID }}
STRIPE_PRO_MONTHLY_PRICE_ID=${{ secrets.STRIPE_PRO_MONTHLY_PRICE_ID }}
STRIPE_PRO_ANNUAL_PRICE_ID=${{ secrets.STRIPE_PRO_ANNUAL_PRICE_ID }}
STRIPE_WEBHOOK_SECRET=${{ secrets.STRIPE_WEBHOOK_SECRET }}
FRONTEND_URL=${{ secrets.FRONTEND_URL }}
GEMINI_API_KEY=${{ secrets.GEMINI_API_KEY }}
GOOGLE_CLOUD_CREDENTIALS_JSON=${{ secrets.GOOGLE_CLOUD_CREDENTIALS_JSON }}
POPPLER_PATH=/usr/bin/
EOF
```

## Implementation Notes

1. The Google Forms service is already configured to read from `GOOGLE_CLOUD_CREDENTIALS_JSON`
2. No additional dependencies needed - Google API client libraries are already in requirements.txt
3. The service gracefully handles missing credentials by logging warnings
4. Assignment logging works independently and doesn't require Google credentials