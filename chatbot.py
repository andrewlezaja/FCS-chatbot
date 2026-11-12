"""
Maintenance-history chatbot: Claude with four read-only SQL tools over the
local MaintainX snapshot (db/mx_data.db, or db/demo.db if that's missing).

Run: python3 chatbot.py
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Manual text can contain characters the Windows console can't print.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = Path(__file__).parent
REAL_DB_PATH = PROJECT_DIR / "db" / "mx_data.db"
DEMO_DB_PATH = PROJECT_DIR / "db" / "demo.db"
MODEL = "claude-sonnet-5"

load_dotenv(PROJECT_DIR / ".env")

# MX_DB_PATH wins; otherwise the real snapshot if present, else the demo data.
DB_PATH = Path(
    os.environ.get("MX_DB_PATH")
    or (REAL_DB_PATH if REAL_DB_PATH.exists() else DEMO_DB_PATH)
)
if not DB_PATH.exists():
    # sqlite3.connect would otherwise create an empty file.
    raise FileNotFoundError(
        f"No database at {DB_PATH}. Run `python3 demo/build_demo_db.py` for the "
        "demo dataset, or `python3 sync.py` (needs MAINTAINX_API_KEY) for real data."
    )
USING_DEMO_DB = DB_PATH.resolve() == DEMO_DB_PATH.resolve()

# Sonnet 5 pricing, USD per million tokens.
PRICE_INPUT_PER_MTOK = 3.00
PRICE_OUTPUT_PER_MTOK = 15.00

# Token usage across every API call in this process (shown in the sidebar).
USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}


def usage_cost_usd():
    """Estimated cost. Cache reads bill at 0.1x input, cache writes at 1.25x."""
    in_rate = PRICE_INPUT_PER_MTOK / 1_000_000
    out_rate = PRICE_OUTPUT_PER_MTOK / 1_000_000
    return (
        USAGE["input_tokens"] * in_rate
        + USAGE["cache_read_input_tokens"] * in_rate * 0.1
        + USAGE["cache_creation_input_tokens"] * in_rate * 1.25
        + USAGE["output_tokens"] * out_rate
    )


# check_same_thread=False because Streamlit reruns on worker threads (reads only).
# busy_timeout so a read during an in-app refresh waits instead of erroring.
def _connect(db_path):
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 5000")
    return c


conn = _connect(DB_PATH)


def reload_db(db_path):
    """Switch to a different DB file (used for Streamlit's writable copy)."""
    global conn
    old, conn = conn, _connect(db_path)
    old.close()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """\
You are a maintenance-history assistant for a manufacturing company, meant to \
be a first line of defense when something breaks on the floor: someone with an \
active problem should be able to ask you before calling a technician, and get \
either a grounded answer or a clear "I don't have that." You have tool access \
to a local database synced from their MaintainX CMMS.

Scope and honesty constraints:
- Asset coverage is org-wide -- list_assets returns every machine/asset MaintainX \
knows about, including equipment with zero logged work orders so far. An asset \
having no work order history does NOT mean the machine doesn't exist or is \
unimportant; it just means nothing has been logged against it yet. Only say a \
machine "doesn't exist" if it's genuinely absent from list_assets, and always \
call list_assets before concluding that, since the user's name for a machine \
(nickname, line name) may not match its exact asset name in the database.
- Assets in this org are not always nested under their parent machine via a \
formal parent/child link -- many components (e.g. "Capstan (M1)", "Electrical \
Cabinet (M1)", "Take-up (M1)") are separate top-level asset records that share \
a location and a "(M1)"-style name suffix with their machine. Treat that shared \
location/naming pattern as meaningful when figuring out what belongs to which \
machine line, don't rely on parent_id alone.
- Work order volume is currently small and not a random/complete sample -- more \
historical invoices are still being validated and ported into MaintainX over \
time. Call get_reliability_stats or get_work_orders to see current counts \
rather than assuming a number from earlier in the conversation still holds. Do \
NOT state percentages, trends, or "most common issue" claims as if they were \
statistically robust when the underlying count is small -- say things like "in \
the work orders logged so far, X happened N times" rather than implying a firm \
statistical pattern.
- Never invent a date, work order, part, vendor, or duration. Every factual \
claim about what happened, when, to which machine, or how long it took must \
come from a tool call result. If the tools return nothing relevant, say so \
plainly instead of guessing.
- Do NOT compute or imply a repair duration from a work order's created_at/ \
completed_at/service_date timestamps. These records were logged after the fact \
from historical invoices, not tracked live -- there is no start/end time \
captured anywhere in this dataset, only a single service date. There is no \
reliable elapsed-time data; say so if asked "how long does X take."
- get_work_orders returns a "service_date" field -- use THIS as the date of the \
event, not mx_logged_completed_at. service_date is COALESCE(actual_completion_date, \
completed_at): about 60% of work orders have a manually-entered "Actual \
Completion Date" custom field that records when the repair really happened, \
which can differ from mx_logged_completed_at (when the record was typed into \
MaintainX from an old invoice) by weeks or months. service_date_is_confirmed \
tells you which case you're in (true = real Actual Completion Date, false = \
falling back to the MX logging date, which is a weaker signal). When you cite a \
date to the user, use service_date, and if service_date_is_confirmed is false, \
say the date is approximate / from when it was logged rather than stating it as \
precise.
- When you reference a specific past event, cite the work order title and \
service_date so the user can verify it in MaintainX.
- Component-level detail (a specific roller, motor, sensor, etc.) is often only \
findable in the free-text description field of a work order, not a structured \
field. Use keyword search for it, and be explicit that you're matching against \
notes, not a guaranteed-complete structured record.
- search_manuals searches the actual equipment manuals/schematics/calibration \
guides on file for each machine (extracted from attached PDFs). Only PDFs that \
had a real text layer were indexed -- individual part/assembly drawings mostly \
did not (they're image/CAD drawings with no text), so absence of a hit there \
doesn't mean the answer doesn't exist on paper, only that it's not in this \
searchable set. When you use manual content in an answer, cite the file name \
and page number so it can be verified against the physical/PDF manual. Do not \
present manual instructions as something you've verified works -- present them \
as "the manual for this model says," since you have no way to confirm a manual \
procedure resolved a real issue (that's what work order history is for).
- If someone describes an immediate safety hazard (sparking, smoke, fire, \
exposed live wiring, etc.), your written answer must lead with immediate safety \
action (stop/de-energize the equipment, keep people clear, don't let anyone \
open an energized panel) as the first thing you say, and be clear that \
hands-on electrical inspection needs a qualified technician. This is about \
answer ordering, not tool use, though -- still call get_work_orders/ \
search_manuals for that asset so you can hand the technician useful context \
(e.g. recent related work on the same equipment) underneath the safety \
instructions. Skipping that lookup isn't safer, it's just less useful once the \
area is secured.
- If someone pushes you to guess despite acknowledging you're not sure, you may \
extrapolate from real retrieved data (clearly labeled as a guess, not a \
diagnosis), but do not invent specifics (a part, a fault code, a cause) that \
isn't grounded in an actual tool result.
"""

TOOLS = [
    {
        "name": "list_assets",
        "description": (
            "List every machine/asset in the database with its id, name, "
            "manufacturer, model, and status. Use this to resolve a "
            "user-mentioned machine name/nickname to the exact asset name "
            "before filtering other tools by asset_name."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_work_orders",
        "description": (
            "Search work orders, optionally filtered by asset name (partial "
            "match), a keyword against the title/description text (use this "
            "to find a specific component or symptom mentioned in notes), "
            "and/or a category (e.g. Electrical, Mechanical, Maintenance, "
            "Inspection). Returns an object with a 'work_orders' list (full "
            "details including description text, vendor, categories, and "
            "dates, ordered by service_date) plus 'total_matches', 'returned', "
            "and a 'truncated' flag. If 'truncated' is true, more work orders "
            "match than were returned -- narrow the query (or raise 'limit') "
            "before making any claim that depends on seeing the complete set "
            "(e.g. 'all history for X', counts, 'the first/only time', 'never "
            "happened'); do not treat a truncated list as exhaustive. Use this "
            "both for exact history lookups (sort desc, small limit) and to "
            "gather candidate work orders whose descriptions you can then judge "
            "for similarity to a described symptom."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_name": {
                    "type": "string",
                    "description": "Partial, case-insensitive match against the asset name.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Partial match against work order title or description text.",
                },
                "category": {
                    "type": "string",
                    "description": "Partial match against a work order category label.",
                },
                "order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Order by completed_at. Default desc (most recent first).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return. Default 500 (large enough to return the full history at current data volume; check 'truncated' in the result if you set it lower).",
                },
            },
        },
    },
    {
        "name": "search_manuals",
        "description": (
            "Full-text search over the extracted content of equipment manuals, "
            "electrical schematics, calibration guides, and sensor operating "
            "instructions attached to each asset in MaintainX. Use this for "
            "'how do I fix/calibrate/adjust X' questions, or to look up specs "
            "and procedures for a specific machine. Returns matching page-level "
            "text chunks ranked by relevance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms, e.g. a component or symptom name ('brake calibration', 'DeviceNet fault').",
                },
                "asset_name": {
                    "type": "string",
                    "description": "Partial, case-insensitive match against the asset name, to scope the search to one machine's manuals.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max chunks to return. Default 5.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_reliability_stats",
        "description": (
            "Get aggregate counts of work orders per machine and per "
            "category, optionally scoped to one machine. Use this for "
            "'what are this machine's most frequent issues' or "
            "cross-machine pattern questions. Remember to caveat small "
            "sample sizes per the system instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_name": {
                    "type": "string",
                    "description": "Partial, case-insensitive match against the asset name. Omit for all machines.",
                },
            },
        },
    },
]


def list_assets():
    rows = conn.execute(
        "SELECT id, name, manufacturer, model, status, serial_number FROM assets ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


DEFAULT_WORK_ORDER_LIMIT = 500


def get_work_orders(asset_name=None, keyword=None, category=None, order="desc", limit=DEFAULT_WORK_ORDER_LIMIT):
    # Count without the limit so the result can say whether it was truncated.
    filters = ""
    params = []
    if asset_name:
        filters += " AND a.name LIKE ?"
        params.append(f"%{asset_name}%")
    if keyword:
        filters += " AND (w.title LIKE ? OR w.description LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if category:
        filters += """ AND w.id IN (
            SELECT work_order_id FROM work_order_categories WHERE category LIKE ?
        )"""
        params.append(f"%{category}%")

    total_matches = conn.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT w.id
            FROM work_orders w
            LEFT JOIN assets a ON w.asset_id = a.id
            WHERE 1=1{filters}
            GROUP BY w.id
        )
        """,
        params,
    ).fetchone()[0]

    limit = limit or DEFAULT_WORK_ORDER_LIMIT
    query = f"""
        SELECT w.id, w.title, w.description, w.status, w.type,
               COALESCE(w.actual_completion_date, w.completed_at) AS service_date,
               (w.actual_completion_date IS NOT NULL) AS service_date_is_confirmed,
               w.completed_at AS mx_logged_completed_at, w.created_at, a.name AS asset_name,
               GROUP_CONCAT(DISTINCT c.category) AS categories,
               GROUP_CONCAT(DISTINCT v.name) AS vendors
        FROM work_orders w
        LEFT JOIN assets a ON w.asset_id = a.id
        LEFT JOIN work_order_categories c ON c.work_order_id = w.id
        LEFT JOIN work_order_vendors wv ON wv.work_order_id = w.id
        LEFT JOIN vendors v ON v.id = wv.vendor_id
        WHERE 1=1{filters}
        GROUP BY w.id
        ORDER BY service_date {"ASC" if order == "asc" else "DESC"}
        LIMIT ?
    """
    rows = [dict(r) for r in conn.execute(query, params + [limit]).fetchall()]

    return {
        "work_orders": rows,
        "total_matches": total_matches,
        "returned": len(rows),
        "truncated": total_matches > len(rows),
    }


def _build_fts_query(text):
    """Quote each word and OR them so user text can't act as FTS5 operators."""
    terms = re.findall(r"[A-Za-z0-9]+", text)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def search_manuals(query, asset_name=None, limit=5):
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []

    sql = """
        SELECT mc.file_name, mc.page_number, mc.chunk_text, a.name AS asset_name,
               bm25(manual_chunks) AS rank
        FROM manual_chunks mc
        JOIN assets a ON a.id = mc.asset_id
        WHERE manual_chunks MATCH ?
    """
    params = [fts_query]
    if asset_name:
        sql += " AND a.name LIKE ?"
        params.append(f"%{asset_name}%")
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit or 5)

    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "asset_name": r["asset_name"],
            "file_name": r["file_name"],
            "page_number": r["page_number"],
            "text": r["chunk_text"],
        }
        for r in rows
    ]


def get_reliability_stats(asset_name=None):
    cat_query = """
        SELECT a.name AS asset_name, c.category, COUNT(*) AS count
        FROM work_orders w
        JOIN assets a ON w.asset_id = a.id
        JOIN work_order_categories c ON c.work_order_id = w.id
    """
    totals_query = """
        SELECT a.name AS asset_name, COUNT(*) AS total_work_orders,
               MIN(COALESCE(w.actual_completion_date, w.completed_at)) AS first_recorded,
               MAX(COALESCE(w.actual_completion_date, w.completed_at)) AS most_recent
        FROM work_orders w
        JOIN assets a ON w.asset_id = a.id
    """
    params = []
    if asset_name:
        cat_query += " WHERE a.name LIKE ?"
        totals_query += " WHERE a.name LIKE ?"
        params.append(f"%{asset_name}%")

    cat_query += " GROUP BY a.name, c.category ORDER BY count DESC"
    totals_query += " GROUP BY a.name ORDER BY total_work_orders DESC"

    category_breakdown = [dict(r) for r in conn.execute(cat_query, params).fetchall()]
    totals_by_asset = [dict(r) for r in conn.execute(totals_query, params).fetchall()]

    return {"totals_by_asset": totals_by_asset, "category_breakdown": category_breakdown}


TOOL_FUNCTIONS = {
    "list_assets": lambda **kwargs: list_assets(),
    "get_work_orders": lambda **kwargs: get_work_orders(**kwargs),
    "search_manuals": lambda **kwargs: search_manuals(**kwargs),
    "get_reliability_stats": lambda **kwargs: get_reliability_stats(**kwargs),
}


def run_tool(name, tool_input):
    try:
        result = TOOL_FUNCTIONS[name](**tool_input)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ask(user_message, messages):
    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            # Caches the tools + system prompt prefix.
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        u = response.usage
        USAGE["input_tokens"] += u.input_tokens
        USAGE["output_tokens"] += u.output_tokens
        USAGE["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        USAGE["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            answer = "".join(
                block.text for block in response.content if block.type == "text"
            )
            if response.stop_reason == "max_tokens":
                answer += (
                    "\n\n⚠️ This answer hit the output limit and was cut off — "
                    "what's above may be incomplete. Try asking for a narrower "
                    "slice (e.g. one machine at a time)."
                )
            return answer

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  [calling {block.name}({block.input})]")
            output = run_tool(block.name, block.input)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output}
            )
        messages.append({"role": "user", "content": tool_results})


def main():
    print("MaintainX history chatbot (prototype). Type 'exit' to quit.\n")
    messages = []
    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_message:
            continue
        if user_message.lower() in {"exit", "quit"}:
            break
        answer = ask(user_message, messages)
        print(f"\nAssistant: {answer}\n")


if __name__ == "__main__":
    main()
