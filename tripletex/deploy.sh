#!/bin/bash
set -e

echo "=== DEPLOY TRIPLETEX AGENT ==="

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "FEIL: ANTHROPIC_API_KEY er ikke satt"
    echo "Kjør: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

# ALTERNATIV 1: Google Cloud Run
if command -v gcloud &> /dev/null; then
    echo "Deployer til Google Cloud Run..."
    gcloud run deploy tripletex-agent \
        --source . \
        --region europe-north1 \
        --allow-unauthenticated \
        --memory 1Gi \
        --cpu 2 \
        --timeout 300 \
        --min-instances 1 \
        --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
    echo "Cloud Run deploy ferdig!"

# ALTERNATIV 2: Lokal Docker + Caddy
else
    echo "gcloud ikke funnet — deployer lokalt med Docker..."
    docker build -t tripletex-agent .
    docker stop tripletex-agent 2>/dev/null || true
    docker rm tripletex-agent 2>/dev/null || true
    docker run -d \
        --name tripletex-agent \
        --restart unless-stopped \
        -p 8080:8080 \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
        tripletex-agent
    echo "Lokal deploy ferdig på port 8080"
    echo "Husk: Sett opp Caddy/nginx for HTTPS!"
fi
