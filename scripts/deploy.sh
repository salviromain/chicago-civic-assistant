#!/bin/sh
# Build the image from the Dockerfile (Cloud Build) and deploy it to Cloud Run (Day 13).
#   sh scripts/deploy.sh
# Uploads only what .gcloudignore allows (app/, docs/TABLES.md, requirements.txt,
# Dockerfile). Secrets come from Secret Manager at startup; nothing secret is in the image.
set -eu
PROJECT=gen-lang-client-0110972456   # the billed project (Cloud Run needs billing)
REGION=us-east5                      # Columbus, Ohio: next to Neon's aws-us-east-2
SA="@$PROJECT.iam.gserviceaccount.com"

# One instance: the rate-limit counts live in memory (app/ratelimit.py).
# TRUSTED_PROXIES=1: read the client's address from Google's front end.
# 100 questions a day: about what the free demo key's daily quota allows.
gcloud run deploy civic-api --source . --region "$REGION" --project "$PROJECT" --quiet \
  --build-service-account "projects/$PROJECT/serviceAccounts/civic-build$SA" \
  --service-account "civic-api$SA" --allow-unauthenticated \
  --max-instances 1 --concurrency 8 --cpu 1 --memory 512Mi --timeout 60 \
  --set-env-vars TRUSTED_PROXIES=1,RATE_LIMIT_TOTAL_PER_DAY=100 \
  --set-secrets GEMINI_API_KEY=gemini-demo-key:latest,SERVICE_API_KEY=service-api-key:latest,READONLY_DATABASE_URL=readonly-database-url:latest
