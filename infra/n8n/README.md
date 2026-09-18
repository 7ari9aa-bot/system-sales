# n8n on Railway — deployment (one command when token arrives)

```
cd backend && .venv/bin/python scripts/deploy_n8n.py --token <RAILWAY_API_TOKEN>
```

What the script creates on Railway:
- project "sales-os"
- service "n8n" from docker image `n8nio/n8n:latest`
- env: N8N_BASIC_AUTH, N8N_HOST, WEBHOOK_URL, N8N_ENCRYPTION_KEY
- public domain → set `N8N_WEBHOOK_BASE` back into core .env

Then import the two workflows from infra/n8n/*.json and set the core API
url + service token as workflow variables.
