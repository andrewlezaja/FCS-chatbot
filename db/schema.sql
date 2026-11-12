-- Locations: MaintainX models these hierarchically (e.g. "Manufacturing Floor" -> "M3 Machinery Line")
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    parent_id   INTEGER REFERENCES locations(id)
);

-- Components are often top-level assets rather than children via parent_id.
CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    parent_id     INTEGER REFERENCES assets(id),
    location_id   INTEGER REFERENCES locations(id),
    serial_number TEXT,
    manufacturer  TEXT,
    model         TEXT,
    status        TEXT,     -- e.g. ONLINE / OFFLINE
    asset_types   TEXT,     -- comma-joined labels, e.g. "Strip Armouring Line"
    extra_fields  TEXT,     -- JSON blob of MX custom fields
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS vendors (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    phone_numbers TEXT,     -- comma-joined
    emails        TEXT      -- comma-joined
);

CREATE TABLE IF NOT EXISTS work_orders (
    id            INTEGER PRIMARY KEY,
    sequential_id INTEGER,
    title         TEXT,
    description   TEXT,     -- primary free-text field: the problem + what was done
    asset_id      INTEGER REFERENCES assets(id),
    location_id   INTEGER REFERENCES locations(id),
    status        TEXT,     -- OPEN / IN_PROGRESS / DONE / ON_HOLD
    type          TEXT,     -- REACTIVE / PREVENTIVE / ...
    priority      TEXT,
    created_at    TEXT,
    completed_at  TEXT,     -- when the record was entered into MaintainX -- NOT when the repair happened
    updated_at    TEXT,
    due_date      TEXT,
    external_data TEXT,     -- original invoice reference id, if any
    extra_fields  TEXT,     -- JSON blob of MX custom fields
    actual_completion_date TEXT  -- real repair date, from the "Actual Completion Date" custom field
);

-- A work order can have several categories.
CREATE TABLE IF NOT EXISTS work_order_categories (
    work_order_id INTEGER REFERENCES work_orders(id),
    category      TEXT NOT NULL,
    PRIMARY KEY (work_order_id, category)
);

CREATE TABLE IF NOT EXISTS work_order_vendors (
    work_order_id INTEGER REFERENCES work_orders(id),
    vendor_id     INTEGER REFERENCES vendors(id),
    PRIMARY KEY (work_order_id, vendor_id)
);

-- Original source documents (often the scanned invoice) attached to a work order.
CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY,
    work_order_id INTEGER REFERENCES work_orders(id),
    file_name     TEXT,
    mime_type     TEXT
);

CREATE INDEX IF NOT EXISTS idx_work_orders_asset_id ON work_orders(asset_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_completed_at ON work_orders(completed_at);
CREATE INDEX IF NOT EXISTS idx_assets_parent_id ON assets(parent_id);

-- Manuals/schematics/etc. attached directly to an asset in MaintainX.
CREATE TABLE IF NOT EXISTS asset_attachments (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER REFERENCES assets(id),
    file_name   TEXT,
    mime_type   TEXT,
    local_path  TEXT,     -- where the downloaded file lives on disk
    extracted   INTEGER DEFAULT 0   -- 0 = pending/failed, 1 = indexed, 2 = no text layer
);

-- One row per PDF page with extractable text (no OCR).
CREATE VIRTUAL TABLE IF NOT EXISTS manual_chunks USING fts5(
    chunk_text,
    asset_id UNINDEXED,
    attachment_id UNINDEXED,
    file_name UNINDEXED,
    page_number UNINDEXED
);
