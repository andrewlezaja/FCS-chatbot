"""
Syncs MaintainX work orders, assets, vendors, locations, and asset manuals
into db/mx_data.db.

Run: python3 sync.py
"""

import json
import os
import sqlite3
import time
from pathlib import Path

import pypdf
import requests
from dotenv import load_dotenv

BASE_URL = "https://api.getmaintainx.com/v1"
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "db" / "mx_data.db"
SCHEMA_PATH = PROJECT_DIR / "db" / "schema.sql"
MANUALS_DIR = PROJECT_DIR / "manuals"

load_dotenv(PROJECT_DIR / ".env")

session = requests.Session()
session.headers.update({"Accept": "application/json"})


# MaintainX allows 100 requests per rolling window and reports the budget in
# X-Rate-Limit-Remaining / X-Rate-Limit-Reset headers.
MAX_RETRIES = 5


def _reset_wait(resp, default):
    """Seconds until the rate-limit window resets, plus 1s of slack."""
    reset = resp.headers.get("X-Rate-Limit-Reset") or resp.headers.get("Retry-After")
    try:
        return float(reset) + 1
    except (TypeError, ValueError):
        return default


def api_get(path, params=None):
    # Read per call so the Streamlit app can set it from secrets after import.
    api_key = os.environ.get("MAINTAINX_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MAINTAINX_API_KEY is not set (put it in .env, or in the Streamlit Secrets panel)"
        )
    session.headers["Authorization"] = f"Bearer {api_key}"
    for attempt in range(MAX_RETRIES):
        resp = session.get(f"{BASE_URL}{path}", params=params, timeout=30)
        if resp.status_code == 429 and attempt < MAX_RETRIES - 1:
            wait = _reset_wait(resp, default=2 ** attempt)
            print(f"  rate limited (429); waiting {wait:.0f}s for reset...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        # Out of budget: wait before the next call instead of hitting a 429.
        if resp.headers.get("X-Rate-Limit-Remaining") == "0":
            time.sleep(_reset_wait(resp, default=1))
        return resp.json()


def paginate(path, list_key, limit=50):
    """Yields every item from a cursor-paginated MaintainX list endpoint."""
    cursor = None
    while True:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = api_get(path, params=params)
        items = data.get(list_key, [])
        if not items:
            break
        yield from items
        cursor = data.get("nextCursor")
        if not cursor:
            break


def fetch_all_work_order_details():
    """The list endpoint omits categories, vendors, and custom fields, so
    fetch each work order's detail."""
    details = []
    for wo_summary in paginate("/workorders", "workOrders"):
        detail = api_get(f"/workorders/{wo_summary['id']}")["workOrder"]
        details.append(detail)
    return details


def fetch_all_asset_ids():
    """Every asset in the org, including machines with no work orders yet."""
    return {a["id"] for a in paginate("/assets", "assets")}


def fetch_assets_with_ancestors(asset_ids, already_known=frozenset()):
    """Fetch each asset and its parent chain, skipping ids in already_known."""
    assets = {}
    to_fetch = set(asset_ids) - set(already_known)
    while to_fetch:
        asset_id = to_fetch.pop()
        if asset_id in assets:
            continue
        asset = api_get(f"/assets/{asset_id}")["asset"]
        assets[asset_id] = asset
        parent_id = asset.get("parentId")
        if parent_id and parent_id not in assets and parent_id not in already_known:
            to_fetch.add(parent_id)
    return assets


def fetch_vendors(vendor_ids):
    vendors = {}
    for vendor_id in vendor_ids:
        vendors[vendor_id] = api_get(f"/vendors/{vendor_id}")["vendor"]
    return vendors


def fetch_all_locations():
    return {loc["id"]: loc for loc in paginate("/locations", "locations")}


def init_db(conn):
    conn.executescript(SCHEMA_PATH.read_text())


def load_locations(conn, locations):
    for loc in locations.values():
        conn.execute(
            """INSERT INTO locations (id, name, description, parent_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, description=excluded.description, parent_id=excluded.parent_id""",
            (loc["id"], loc["name"], loc.get("description"), loc.get("parentId")),
        )


def load_assets(conn, assets):
    for asset in assets.values():
        status = (asset.get("status") or {}).get("status")
        asset_types = ", ".join(asset.get("assetTypes") or [])
        conn.execute(
            """INSERT INTO assets
                 (id, name, description, parent_id, location_id, serial_number,
                  manufacturer, model, status, asset_types, extra_fields, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, description=excluded.description, parent_id=excluded.parent_id,
                 location_id=excluded.location_id, serial_number=excluded.serial_number,
                 manufacturer=excluded.manufacturer, model=excluded.model, status=excluded.status,
                 asset_types=excluded.asset_types, extra_fields=excluded.extra_fields,
                 updated_at=excluded.updated_at""",
            (
                asset["id"], asset["name"], asset.get("description"), asset.get("parentId"),
                asset.get("locationId"), asset.get("serialNumber"), asset.get("manufacturer"),
                asset.get("model"), status, asset_types,
                json.dumps(asset.get("extraFields") or {}),
                asset.get("createdAt"), asset.get("updatedAt"),
            ),
        )


def load_vendors(conn, vendors):
    for vendor in vendors.values():
        conn.execute(
            """INSERT INTO vendors (id, name, description, phone_numbers, emails)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 phone_numbers=excluded.phone_numbers, emails=excluded.emails""",
            (
                vendor["id"], vendor["name"], vendor.get("description"),
                ", ".join(vendor.get("phoneNumbers") or []),
                ", ".join(vendor.get("emails") or []),
            ),
        )


def load_work_orders(conn, work_orders):
    for wo in work_orders:
        external_data = wo.get("externalData")
        if isinstance(external_data, (dict, list)):
            external_data = json.dumps(external_data)
        extra_fields = wo.get("extraFields") or {}
        # completed_at is when the record was entered; this is the real repair date.
        actual_completion_date = extra_fields.get("Actual Completion Date")
        conn.execute(
            """INSERT INTO work_orders
                 (id, sequential_id, title, description, asset_id, location_id, status, type,
                  priority, created_at, completed_at, updated_at, due_date, external_data,
                  extra_fields, actual_completion_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description, asset_id=excluded.asset_id,
                 location_id=excluded.location_id, status=excluded.status, type=excluded.type,
                 priority=excluded.priority, completed_at=excluded.completed_at,
                 updated_at=excluded.updated_at, due_date=excluded.due_date,
                 external_data=excluded.external_data, extra_fields=excluded.extra_fields,
                 actual_completion_date=excluded.actual_completion_date""",
            (
                wo["id"], wo.get("sequentialId"), wo.get("title"), wo.get("description"),
                wo.get("assetId"), wo.get("locationId"), wo.get("status"), wo.get("type"),
                wo.get("priority"), wo.get("createdAt"), wo.get("completedAt"), wo.get("updatedAt"),
                wo.get("dueDate"), external_data, json.dumps(extra_fields), actual_completion_date,
            ),
        )

        conn.execute("DELETE FROM work_order_categories WHERE work_order_id = ?", (wo["id"],))
        for category in wo.get("categories") or []:
            conn.execute(
                "INSERT INTO work_order_categories (work_order_id, category) VALUES (?, ?)",
                (wo["id"], category),
            )

        conn.execute("DELETE FROM work_order_vendors WHERE work_order_id = ?", (wo["id"],))
        for vendor_id in wo.get("vendorIds") or []:
            conn.execute(
                "INSERT INTO work_order_vendors (work_order_id, vendor_id) VALUES (?, ?)",
                (wo["id"], vendor_id),
            )

        conn.execute("DELETE FROM attachments WHERE work_order_id = ?", (wo["id"],))
        for att in wo.get("attachments") or []:
            conn.execute(
                "INSERT INTO attachments (id, work_order_id, file_name, mime_type) VALUES (?, ?, ?, ?)",
                (att["id"], wo["id"], att.get("fileName"), att.get("mimeType")),
            )


def extract_pdf_pages(conn, asset_id, attachment_id, file_name, local_path):
    """Replace one PDF's text chunks (one row per page). Returns pages with text."""
    conn.execute("DELETE FROM manual_chunks WHERE attachment_id = ?", (attachment_id,))
    reader = pypdf.PdfReader(str(local_path))
    pages_with_text = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        conn.execute(
            """INSERT INTO manual_chunks (chunk_text, asset_id, attachment_id, file_name, page_number)
               VALUES (?, ?, ?, ?, ?)""",
            (text, asset_id, attachment_id, file_name, page_number),
        )
        pages_with_text += 1
    return pages_with_text


# asset_attachments.extracted: 0 = pending or failed (retry), 1 = indexed,
# 2 = parsed but no text layer (don't retry).
EXTRACT_PENDING, EXTRACT_DONE, EXTRACT_NO_TEXT = 0, 1, 2


def sync_manuals(conn, assets):
    """Download each asset's PDFs and index their text. Download URLs expire
    after about an hour, so this runs in the same sync that fetched them."""
    MANUALS_DIR.mkdir(exist_ok=True)
    processed = indexed = 0

    for asset in assets.values():
        asset_id = asset["id"]
        for att in asset.get("attachments") or []:
            att_id = att["id"]
            file_name = att.get("fileName")
            mime_type = att.get("mimeType")

            already_done = conn.execute(
                "SELECT extracted FROM asset_attachments WHERE id = ?", (att_id,)
            ).fetchone()
            if already_done and already_done[0] in (EXTRACT_DONE, EXTRACT_NO_TEXT):
                continue

            local_path = None
            extracted_flag = EXTRACT_PENDING

            if mime_type == "application/pdf":
                processed += 1
                local_path = MANUALS_DIR / f"{asset_id}_{att_id}_{file_name}"
                try:
                    resp = requests.get(att["url"], timeout=60)
                    resp.raise_for_status()
                    local_path.write_bytes(resp.content)
                    pages_with_text = extract_pdf_pages(conn, asset_id, att_id, file_name, local_path)
                    extracted_flag = EXTRACT_DONE if pages_with_text > 0 else EXTRACT_NO_TEXT
                    if extracted_flag == EXTRACT_DONE:
                        indexed += 1
                    note = f"{pages_with_text} page(s) with extractable text" if pages_with_text else "no extractable text (likely scanned), won't retry"
                    print(f"    {file_name}: {note}")
                except Exception as e:
                    print(f"    WARNING: failed to process {file_name} (asset {asset_id}): {e}")
                    local_path = None
            else:
                print(f"    {file_name}: skipped ({mime_type or 'unknown type'}, not a PDF)")

            conn.execute(
                """INSERT INTO asset_attachments (id, asset_id, file_name, mime_type, local_path, extracted)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     file_name=excluded.file_name, mime_type=excluded.mime_type,
                     local_path=excluded.local_path, extracted=excluded.extracted""",
                (att_id, asset_id, file_name, mime_type, str(local_path) if local_path else None, extracted_flag),
            )

    return {"manuals_processed": processed, "manuals_indexed": indexed}


def _delete_not_in(conn, table, id_column, keep_ids):
    """Delete rows whose id isn't in keep_ids. Skipped when keep_ids is empty
    so a failed fetch can't wipe the table."""
    if not keep_ids:
        print(f"    WARNING: nothing fetched for {table}; skipping prune to avoid a wipe")
        return 0
    keep = list(keep_ids)
    placeholders = ",".join("?" * len(keep))
    return conn.execute(
        f"DELETE FROM {table} WHERE {id_column} NOT IN ({placeholders})", keep
    ).rowcount


def _prune_work_order_children(conn, wo_ids):
    """Delete child rows of work orders that no longer exist."""
    if not wo_ids:
        return
    keep = list(wo_ids)
    placeholders = ",".join("?" * len(keep))
    for child in ("work_order_categories", "work_order_vendors", "attachments"):
        conn.execute(
            f"DELETE FROM {child} WHERE work_order_id NOT IN ({placeholders})", keep
        )


def prune_stale(conn, work_orders, assets, vendors, locations):
    """Delete local records that are no longer in MaintainX (children first)."""
    wo_ids = {wo["id"] for wo in work_orders}
    asset_ids = set(assets.keys())
    vendor_ids = set(vendors.keys())
    location_ids = set(locations.keys())

    _prune_work_order_children(conn, wo_ids)
    removed_wo = _delete_not_in(conn, "work_orders", "id", wo_ids)

    if asset_ids:
        keep = list(asset_ids)
        placeholders = ",".join("?" * len(keep))
        conn.execute(
            f"DELETE FROM manual_chunks WHERE asset_id NOT IN ({placeholders})", keep
        )
        conn.execute(
            f"DELETE FROM asset_attachments WHERE asset_id NOT IN ({placeholders})", keep
        )
    removed_assets = _delete_not_in(conn, "assets", "id", asset_ids)

    removed_vendors = _delete_not_in(conn, "vendors", "id", vendor_ids)
    removed_locations = _delete_not_in(conn, "locations", "id", location_ids)

    print(
        f"  pruned {removed_wo} work order(s), {removed_assets} asset(s), "
        f"{removed_vendors} vendor(s), {removed_locations} location(s) "
        "no longer in MaintainX"
    )


def refresh_work_orders(conn):
    """Fast refresh for the Streamlit app: work orders, their vendors, and any
    new assets they reference. Assets and locations aren't pruned here since
    their full lists aren't fetched."""
    work_orders = fetch_all_work_order_details()
    vendor_ids = {vid for wo in work_orders for vid in (wo.get("vendorIds") or [])}
    vendors = fetch_vendors(vendor_ids)

    known_asset_ids = {row[0] for row in conn.execute("SELECT id FROM assets")}
    referenced = {wo["assetId"] for wo in work_orders if wo.get("assetId")}
    new_assets = fetch_assets_with_ancestors(
        referenced - known_asset_ids, already_known=known_asset_ids
    )

    load_assets(conn, new_assets)
    load_vendors(conn, vendors)
    load_work_orders(conn, work_orders)

    wo_ids = {wo["id"] for wo in work_orders}
    _prune_work_order_children(conn, wo_ids)
    removed_wo = _delete_not_in(conn, "work_orders", "id", wo_ids)
    removed_vendors = _delete_not_in(conn, "vendors", "id", vendor_ids)
    conn.commit()

    return {
        "work_orders": len(work_orders),
        "new_assets": len(new_assets),
        "pruned_work_orders": removed_wo,
        "pruned_vendors": removed_vendors,
    }


def refresh_full(conn):
    """Full sync on an existing connection. Takes minutes because of the
    rate limit."""
    print("Fetching work orders (with full detail)...")
    work_orders = fetch_all_work_order_details()
    print(f"  {len(work_orders)} work orders")

    vendor_ids = {vid for wo in work_orders for vid in (wo.get("vendorIds") or [])}

    print("Fetching full asset list for the org...")
    wo_asset_ids = {wo["assetId"] for wo in work_orders if wo.get("assetId")}
    all_asset_ids = fetch_all_asset_ids() | wo_asset_ids
    print(f"  {len(all_asset_ids)} assets (org-wide, including equipment with no work orders yet)")

    print("Fetching asset detail (+ ancestor chain)...")
    assets = fetch_assets_with_ancestors(all_asset_ids)
    print(f"  {len(assets)} assets")

    print("Fetching vendors...")
    vendors = fetch_vendors(vendor_ids)
    print(f"  {len(vendors)} vendors")

    print("Fetching locations...")
    locations = fetch_all_locations()
    print(f"  {len(locations)} locations")

    init_db(conn)
    load_locations(conn, locations)
    load_assets(conn, assets)
    load_vendors(conn, vendors)
    load_work_orders(conn, work_orders)

    print("Pruning records deleted from MaintainX...")
    prune_stale(conn, work_orders, assets, vendors, locations)
    conn.commit()

    print("Downloading & extracting asset manuals (PDF attachments)...")
    manuals = sync_manuals(conn, assets)
    conn.commit()

    return {
        "work_orders": len(work_orders),
        "assets": len(assets),
        "vendors": len(vendors),
        "locations": len(locations),
        **manuals,
    }


def main():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        refresh_full(conn)
    finally:
        conn.close()

    print(f"Done. Database written to {DB_PATH}")


if __name__ == "__main__":
    main()
