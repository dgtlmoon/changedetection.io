# Neon.tech Database Setup Guide

This guide walks you through creating a Neon.tech PostgreSQL database for TicketWatch.

## Prerequisites

- A Neon.tech account (free tier available)

## Step 1: Create Neon.tech Account

1. Go to [https://neon.tech](https://neon.tech)
2. Click "Sign Up" and create an account (GitHub OAuth available)
3. Verify your email if required

## Step 2: Create a New Project

1. From the Neon Console dashboard, click **"New Project"**
2. Configure the project:
   - **Project name**: `ticketwatch` (or your preferred name)
   - **Postgres version**: `16` (latest stable)
   - **Region**: Choose closest to your Fly.io region
     - If deploying to `ord` (Chicago), select **US East** or closest available
   - **Compute size**: Start with **0.25 CU** (free tier)
3. Click **"Create Project"**

## Step 3: Get Connection String

After project creation, Neon displays your connection details:

1. In your project dashboard, find the **"Connection Details"** panel
2. Select **"Connection string"** tab
3. Copy the connection string in this format:
   ```
   postgresql://username:password@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

### Connection String Components

| Component | Description |
|-----------|-------------|
| `username` | Your Neon database user (auto-generated) |
| `password` | Your database password (keep secure!) |
| `ep-xxxxx` | Your endpoint ID |
| `us-east-2.aws.neon.tech` | Neon host region |
| `neondb` | Default database name |
| `sslmode=require` | Required for secure connection |

## Step 4: Store Connection String

### For Local Development

Create a `.env` file in the project root (this file is gitignored):

```bash
DATABASE_URL=postgresql://username:password@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
```

### For Fly.io Deployment

Set as a secret (covered in US-006):

```bash
fly secrets set DATABASE_URL="postgresql://username:password@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require"
```

## Step 5: Verify Connection (Optional)

Test your connection using `psql`:

```bash
psql "postgresql://username:password@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require"
```

Or using Python:

```python
import psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cursor = conn.cursor()
cursor.execute('SELECT version();')
print(cursor.fetchone())
conn.close()
```

## Database Schema

The following tables will be created by US-003 (PostgreSQL Storage Adapter):

### watches table
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| url | TEXT | URL to monitor |
| title | TEXT | Watch title |
| tag | TEXT | Category tag |
| check_interval | INTEGER | Check frequency (seconds) |
| last_checked | TIMESTAMP | Last check time |
| last_changed | TIMESTAMP | Last change detected |
| paused | BOOLEAN | Whether watch is paused |
| created_at | TIMESTAMP | Record creation time |

### snapshots table
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| watch_id | UUID | Foreign key to watches |
| content_hash | TEXT | Hash of page content |
| captured_at | TIMESTAMP | Snapshot capture time |
| extracted_prices | JSONB | Extracted price data |
| extracted_availability | TEXT | Availability status |

## Neon.tech Free Tier Limits

- 0.5 GB storage
- 191 compute hours/month
- Auto-suspend after 5 minutes of inactivity (wakes on connection)
- Unlimited projects

## Troubleshooting

### Connection Refused
- Ensure `sslmode=require` is in your connection string
- Check if endpoint is suspended (free tier auto-suspends)
- Verify IP is not blocked (Neon allows all IPs by default)

### Authentication Failed
- Double-check username and password
- Regenerate password in Neon Console if needed

### Timeout on First Connection
- Free tier endpoints auto-suspend; first connection takes 2-5 seconds to wake

## Next Steps

Once database is created:
1. Store `DATABASE_URL` in `.env` for local development
2. Proceed to US-003: Implement PostgreSQL Storage Adapter
