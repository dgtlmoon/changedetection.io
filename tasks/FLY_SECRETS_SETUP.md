# Fly.io Secrets Configuration Guide

This guide covers setting up Fly.io secrets for the TicketWatch deployment. Secrets are environment variables that are encrypted and securely stored by Fly.io.

## Prerequisites

1. Fly.io CLI installed: https://fly.io/docs/hands-on/install-flyctl/
2. Logged in: `fly auth login`
3. App created (see US-005): `fly apps create`

## Required Secrets

### 1. DATABASE_URL (Required)

PostgreSQL connection string from Neon.tech.

```bash
fly secrets set DATABASE_URL="postgresql://username:password@ep-xxxxx.region.aws.neon.tech/neondb?sslmode=require" --app changedetection-io-z08mj
```

**Where to get it:**
- Log into [Neon.tech Console](https://console.neon.tech)
- Select your project
- Go to **Connection Details**
- Copy the connection string (use the pooled connection for production)

### 2. SLACK_WEBHOOK_URL (Required)

Slack incoming webhook URL for price/availability alerts.

```bash
fly secrets set SLACK_WEBHOOK_URL="YOUR_SLACK_WEBHOOK_URL_HERE" --app changedetection-io-z08mj
```

**Where to get it:**
1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Create a new app or select existing
3. Enable **Incoming Webhooks**
4. Click **Add New Webhook to Workspace**
5. Select the channel for notifications
6. Copy the Webhook URL

### 3. PROXY_LIST_PATH (Optional)

Path to a file containing proxy servers for rotation (one per line).

```bash
fly secrets set PROXY_LIST_PATH="/datastore/proxies.txt" --app changedetection-io-z08mj
```

**Note:** If using proxies, upload the proxy list file to your mounted volume:
```bash
# SSH into the app and create the file
fly ssh console --app changedetection-io-z08mj
echo "http://proxy1:port" >> /datastore/proxies.txt
echo "http://proxy2:port" >> /datastore/proxies.txt
```

### 4. SALTED_PASS (Optional)

Password hash for UI authentication. If not set, the UI will be publicly accessible.

```bash
# First, generate the hash locally
python -c "import hashlib; print(hashlib.sha256('your-secure-password'.encode()).hexdigest())"

# Then set the secret
fly secrets set SALTED_PASS="your-generated-hash-here" --app changedetection-io-z08mj
```

**Security Note:** Use a strong, unique password. The hash is a SHA-256 digest of your password.

## Setting All Secrets at Once

You can set multiple secrets in a single command:

```bash
fly secrets set \
  DATABASE_URL="postgresql://..." \
  SLACK_WEBHOOK_URL="https://hooks.slack.com/..." \
  SALTED_PASS="hash..." \
  --app changedetection-io-z08mj
```

## Verifying Secrets

List all configured secrets (values are hidden):

```bash
fly secrets list --app changedetection-io-z08mj
```

Expected output:
```
NAME              DIGEST                            CREATED AT
DATABASE_URL      xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  1h ago
SLACK_WEBHOOK_URL xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  1h ago
SALTED_PASS       xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  1h ago
```

## Updating Secrets

To update a secret, simply set it again:

```bash
fly secrets set SLACK_WEBHOOK_URL="https://hooks.slack.com/new-url" --app changedetection-io-z08mj
```

The app will automatically restart with the new value.

## Removing Secrets

To unset a secret:

```bash
fly secrets unset PROXY_LIST_PATH --app changedetection-io-z08mj
```

## Troubleshooting

### Secret Not Available in App

1. Verify the secret is set: `fly secrets list`
2. Check app logs: `fly logs --app changedetection-io-z08mj`
3. Restart the app: `fly apps restart changedetection-io-z08mj`

### Database Connection Fails

1. Ensure Neon.tech project is active (not suspended)
2. Verify the connection string includes `?sslmode=require`
3. Check Neon dashboard for connection limits

### Slack Notifications Not Working

1. Verify webhook URL is correct
2. Check the Slack channel permissions
3. Test webhook manually:
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test message"}' \
     "YOUR_WEBHOOK_URL"
   ```

## Next Steps

After configuring secrets:
1. Deploy the application: `fly deploy --config tasks/fly.toml`
2. Check deployment status: `fly status --app changedetection-io-z08mj`
3. View logs: `fly logs --app changedetection-io-z08mj`
