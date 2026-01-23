-- =============================================================================
-- ATC Page Monitor - PostgreSQL Schema V2
-- =============================================================================
--
-- This SQL script creates the complete database schema for the ATC Page Monitor
-- ticketing intelligence platform on Neon.tech (PostgreSQL 16).
--
-- Tables:
--   - schema_version: Schema migration tracking
--   - users: User accounts with role-based access (admin/viewer)
--   - tags: Event categories with Slack webhook routing
--   - events: Tracked events with pricing and availability data
--   - event_tags: Many-to-many relationship between events and tags
--   - price_history: Historical price tracking
--   - availability_history: Historical sold-out tracking
--   - notification_log: Notification audit log for debugging
--   - snapshots: Page content snapshots (legacy compatibility)
--
-- Usage:
--   1. Connect to your Neon.tech database
--   2. Run this script: psql -h <host> -U <user> -d <database> -f schema_v2.sql
--
-- Schema Version: 2
-- =============================================================================

-- Schema Version Tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    description TEXT
);

-- =============================================================================
-- Users Table
-- =============================================================================
-- Stores user accounts with role-based access control.
-- Roles: 'admin' (full access), 'viewer' (read-only access)

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'viewer')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,

    CONSTRAINT users_email_not_empty CHECK (email <> ''),
    CONSTRAINT users_password_hash_not_empty CHECK (password_hash <> '')
);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- =============================================================================
-- Tags Table
-- =============================================================================
-- Stores event categories/tags with Slack webhook routing.
-- Each tag can have its own Slack webhook URL for targeted notifications.

CREATE TABLE IF NOT EXISTS tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    slack_webhook_url TEXT,
    notification_muted BOOLEAN DEFAULT FALSE,
    color TEXT DEFAULT '#3B82F6',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT tags_name_not_empty CHECK (name <> '')
);

-- Indexes for tags table
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_tags_created_by ON tags(created_by);
CREATE INDEX IF NOT EXISTS idx_tags_notification_muted ON tags(notification_muted);

-- =============================================================================
-- Events Table
-- =============================================================================
-- Stores tracked events with all ticketing data.
-- Includes extracted metadata, pricing, availability, and monitoring config.

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core identification
    url TEXT NOT NULL,

    -- Event metadata (extracted or manual)
    event_name TEXT,
    artist TEXT,
    venue TEXT,
    event_date DATE,
    event_time TIME,

    -- Pricing data
    current_price_low DECIMAL(10, 2),
    current_price_high DECIMAL(10, 2),

    -- Availability
    is_sold_out BOOLEAN DEFAULT FALSE,

    -- Ticket type tracking
    ticket_types JSONB DEFAULT '[]'::jsonb,
    track_specific_types BOOLEAN DEFAULT FALSE,

    -- Monitoring configuration
    check_interval INTEGER DEFAULT 3600,
    paused BOOLEAN DEFAULT FALSE,

    -- CSS selectors for extraction
    include_filters JSONB DEFAULT '[]'::jsonb,
    css_selectors JSONB DEFAULT '{}'::jsonb,

    -- Request configuration
    headers JSONB DEFAULT '{}'::jsonb,
    fetch_backend TEXT DEFAULT 'playwright',
    processor TEXT DEFAULT 'text_json_diff',

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_checked TIMESTAMP WITH TIME ZONE,
    last_changed TIMESTAMP WITH TIME ZONE,

    -- Extra configuration (extensible)
    extra_config JSONB DEFAULT '{}'::jsonb,

    -- Notification URLs (legacy support)
    notification_urls JSONB DEFAULT '[]'::jsonb,

    CONSTRAINT events_url_not_empty CHECK (url <> '')
);

-- Indexes for events table
CREATE INDEX IF NOT EXISTS idx_events_url ON events(url);
CREATE INDEX IF NOT EXISTS idx_events_event_name ON events(event_name);
CREATE INDEX IF NOT EXISTS idx_events_artist ON events(artist);
CREATE INDEX IF NOT EXISTS idx_events_venue ON events(venue);
CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_is_sold_out ON events(is_sold_out);
CREATE INDEX IF NOT EXISTS idx_events_paused ON events(paused);
CREATE INDEX IF NOT EXISTS idx_events_last_checked ON events(last_checked);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);

-- =============================================================================
-- Event-Tags Junction Table
-- =============================================================================
-- Many-to-many relationship between events and tags.
-- An event can have multiple tags, and a tag can be assigned to multiple events.

CREATE TABLE IF NOT EXISTS event_tags (
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,

    PRIMARY KEY (event_id, tag_id)
);

-- Indexes for event_tags table
CREATE INDEX IF NOT EXISTS idx_event_tags_event_id ON event_tags(event_id);
CREATE INDEX IF NOT EXISTS idx_event_tags_tag_id ON event_tags(tag_id);

-- =============================================================================
-- Price History Table
-- =============================================================================
-- Tracks price changes over time for analysis and alerts.
-- Records both low and high prices, optionally by ticket type.

CREATE TABLE IF NOT EXISTS price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    price_low DECIMAL(10, 2),
    price_high DECIMAL(10, 2),
    ticket_type TEXT,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for price_history table
CREATE INDEX IF NOT EXISTS idx_price_history_event_id ON price_history(event_id);
CREATE INDEX IF NOT EXISTS idx_price_history_recorded_at ON price_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_price_history_event_recorded ON price_history(event_id, recorded_at DESC);

-- =============================================================================
-- Availability History Table
-- =============================================================================
-- Tracks sold-out status changes over time.
-- Enables restock detection and sell-out analysis.

CREATE TABLE IF NOT EXISTS availability_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    is_sold_out BOOLEAN NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for availability_history table
CREATE INDEX IF NOT EXISTS idx_availability_history_event_id ON availability_history(event_id);
CREATE INDEX IF NOT EXISTS idx_availability_history_recorded_at ON availability_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_availability_history_event_recorded ON availability_history(event_id, recorded_at DESC);

-- =============================================================================
-- Notification Log Table
-- =============================================================================
-- Audit log for all notifications sent.
-- Useful for debugging, metrics, and ensuring delivery.

CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id) ON DELETE SET NULL,
    tag_id UUID REFERENCES tags(id) ON DELETE SET NULL,

    notification_type TEXT NOT NULL CHECK (notification_type IN ('restock', 'price_change', 'sold_out', 'new_event', 'error')),
    webhook_url TEXT,

    -- Request/Response details
    payload JSONB,
    response_status INTEGER,
    response_body TEXT,

    -- Status
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,

    -- Timestamps
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Additional context
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Indexes for notification_log table
CREATE INDEX IF NOT EXISTS idx_notification_log_event_id ON notification_log(event_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_tag_id ON notification_log(tag_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_notification_type ON notification_log(notification_type);
CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at);
CREATE INDEX IF NOT EXISTS idx_notification_log_success ON notification_log(success);

-- =============================================================================
-- Snapshots Table (Legacy Compatibility)
-- =============================================================================
-- Stores page content snapshots for change detection.
-- Maintains compatibility with the MVP schema.

CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    extracted_prices JSONB,
    extracted_availability TEXT,
    content_text TEXT,
    content_url TEXT
);

-- Indexes for snapshots table
CREATE INDEX IF NOT EXISTS idx_snapshots_event_id ON snapshots(event_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_content_hash ON snapshots(content_hash);

-- =============================================================================
-- Record Schema Version
-- =============================================================================

INSERT INTO schema_version (version, description)
VALUES (2, 'ATC Page Monitor schema with users, tags, events, price_history, availability_history, notification_log')
ON CONFLICT (version) DO NOTHING;

-- =============================================================================
-- Sample Data (Optional - Comment out for production)
-- =============================================================================

-- Sample admin user (password: 'admin123' - replace with proper bcrypt hash)
-- INSERT INTO users (id, email, password_hash, role, created_at)
-- VALUES (
--     'a0000000-0000-0000-0000-000000000001',
--     'admin@example.com',
--     '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.XsZ.OFYfL.lC4W',
--     'admin',
--     NOW()
-- ) ON CONFLICT (id) DO NOTHING;

-- Sample tags
-- INSERT INTO tags (id, name, slack_webhook_url, color)
-- VALUES
--     ('b0000000-0000-0000-0000-000000000001', 'concerts', NULL, '#EF4444'),
--     ('b0000000-0000-0000-0000-000000000002', 'comedy', NULL, '#F59E0B'),
--     ('b0000000-0000-0000-0000-000000000003', 'sports', NULL, '#10B981')
-- ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- Verification Query
-- =============================================================================

-- Run this to verify tables were created:
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;

-- Run this to check schema version:
-- SELECT * FROM schema_version;
