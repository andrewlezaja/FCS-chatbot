"""
Builds db/demo.db, a fictional dataset with the same schema as the real
sync, so the app and eval suite run without MaintainX access. The records
are set up so every eval.py case still exercises its failure mode.

Run: python3 demo/build_demo_db.py
"""

import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_DIR / "db" / "schema.sql"
DEMO_DB_PATH = PROJECT_DIR / "db" / "demo.db"

MAKER = "Meridian Wireworks"  # fictional OEM

# (id, name, description, parent_id)
LOCATIONS = [
    (1, "Manufacturing Floor", "Main production hall", None),
    (2, "M1 Machinery Line", None, 1),
    (3, "M2 Machinery Line", None, 1),
    (4, "M3 Machinery Line", None, 1),
    (5, "M4 Machinery Line", None, 1),
    (6, "Large Twister Machinery Line", None, 1),
    (7, "Small Twister Machinery Line", None, 1),
    (8, "Packaging Area", None, 1),
    (9, "Parts Room", None, None),
]

# (id, name, parent_id, location_id, serial, manufacturer, model, status, asset_types)
# Most components are linked to their machine by location and name suffix,
# not parent_id. The M2 brake assembly is the exception.
ASSETS = [
    (101, "Armoring Cable Machine (M1)", None, 2, "AL5-1101", MAKER, "AL-500", "ONLINE", "Strip Armouring Line"),
    (102, "Armoring Cable Machine (M2)", None, 3, "AL5-1102", MAKER, "AL-500", "ONLINE", "Strip Armouring Line"),
    (103, "Armoring Cable Machine (M3)", None, 4, "AL5-1103", MAKER, "AL-500", "ONLINE", "Strip Armouring Line"),
    (104, "Armoring Cable Machine (M4)", None, 5, "AL5-1104", MAKER, "AL-500", "ONLINE", "Strip Armouring Line"),
    (111, "Electrical Cabinet (M1)", None, 2, None, MAKER, "EC-500", "ONLINE", None),
    (112, "Electrical Cabinet (M2)", None, 3, None, MAKER, "EC-500", "ONLINE", None),
    (113, "Electrical Cabinet (M3)", None, 4, None, MAKER, "EC-500", "ONLINE", None),
    (114, "Electrical Cabinet (M4)", None, 5, None, MAKER, "EC-500", "ONLINE", None),
    (121, "Take-up (M1)", None, 2, None, MAKER, "TU-200", "ONLINE", None),
    (122, "Take-up (M2)", None, 3, None, MAKER, "TU-200", "ONLINE", None),
    (123, "Take-up (M3)", None, 4, None, MAKER, "TU-200", "ONLINE", None),
    (131, "Capstan (M3)", None, 4, None, MAKER, "CP-400", "ONLINE", None),
    (141, "Brake Assembly (M2)", 102, 3, None, MAKER, "BK-50", "ONLINE", None),
    # No work orders for these two.
    (151, "Large Twister (LT)", None, 6, "LT-0007", "Halvorsen Machine Co.", "HT-12", "ONLINE", "Twisting Line"),
    (152, "Small Twister (ST)", None, 7, "ST-0003", "Halvorsen Machine Co.", "HT-6", "ONLINE", "Twisting Line"),
    (161, "Label Applicator LA-140", None, 8, "LA140-2291", "Brightline Packaging", "LA-140", "ONLINE", "Labeler"),
]

# (id, name, description, phones, emails)
VENDORS = [
    (201, "Summit Industrial Electric", "Drives, controls, and panel work", "555-0142", "service@summit-electric.example"),
    (202, "Ridgeline Drive Services", "VFD repair and calibration", "555-0187", "dispatch@ridgeline-drives.example"),
]

# actual = real repair date (None if not recorded); logged = completed_at.
WORK_ORDERS = [
    dict(asset=101, title="Intermittent Code 7 fault on main drive (M1)",
         desc='Technician: "Line #1 drive dropping out with Code 7 Fault (network loss). '
              'Reseated DeviceNet connector at drive and cabinet, checked terminating resistor. '
              'Ran 2 hrs without fault."',
         actual="2025-11-18", logged="2026-01-09T15:20:00Z", cats=["Electrical"], vendors=[201]),
    dict(asset=111, title="DeviceNet card replaced – recurring Code 7 Fault (M1)",
         desc='Technician: "Code 7 Fault returned on Line #1. DeviceNet scanner card in electrical '
              'cabinet showing red NS LED. Replaced DeviceNet card, re-downloaded node config, '
              'verified comms to drive and HMI. Line running."',
         actual="2026-02-10", logged="2026-02-11T14:05:00Z", cats=["Electrical"], vendors=[201]),
    dict(asset=101, title="Braking resistor overheating – troubleshoot & repair (M1)",
         desc='Technician: "Braking resistor on Line #1 running hot and smelled burnt. Measured '
              'resistance out of spec. Replaced braking resistor, checked decel ramp in drive '
              'parameters. Line running good."',
         actual="2026-03-05", logged="2026-06-23T13:05:35Z", cats=["Electrical"], vendors=[201]),
    dict(asset=101, title="Troubleshoot M1 + replace resistor",
         desc='Technician: "Line #1 tripping on overvoltage during stops. Found bad braking '
              'resistor. Replaced with new. No material problems found."',
         actual="2024-09-12", logged="2025-04-02T10:00:00Z", cats=["Electrical"], vendors=[202]),
    dict(asset=101, title="Line calibration adjustment (M1)",
         desc='Technician: "Calibrated Line #1 HMI screen, verified VFD output 2. Line was running '
              'at 30% on output 2 with a full reel. Adjusted gain, now tracks correctly. Also '
              'adjusted the roller plates on the armor head -- left side plate was rubbing."',
         actual="2025-08-14", logged="2025-08-15T09:30:00Z", cats=["Calibration", "Mechanical"], vendors=[202]),
    dict(asset=121, title="Take-up traverse not reversing (M1)",
         desc='Technician: "Traverse limit switch on take-up stuck. Cleaned and replaced switch '
              'actuator arm."',
         actual=None, logged="2025-05-20T16:45:00Z", cats=["Mechanical"], vendors=[]),
    dict(asset=121, title="Take-up dancer arm noisy (M1)",
         desc='Technician: "Greased dancer arm pivot, replaced worn bushing."',
         actual="2025-01-28", logged="2025-03-11T11:00:00Z", cats=["Mechanical"], vendors=[]),
    dict(asset=111, title="Cabinet cooling fan replaced (M1)",
         desc='Technician: "Cabinet over-temp alarm. Filter clogged and fan bearing seized. '
              'Replaced fan and filter."',
         actual=None, logged="2025-07-02T13:15:00Z", cats=["Electrical"], vendors=[]),
    dict(asset=101, title="Armor head tape break detector false trips (M1)",
         desc='Technician: "Tape break sensor misaligned after head change. Re-aimed and re-taught '
              'sensor per guide."',
         actual="2026-04-22", logged="2026-04-22T18:00:00Z", cats=["Calibration"], vendors=[]),
    dict(asset=102, title="Brake output calibration (M2)",
         desc='Technician: "Line #2 brake grabbing at low speed. Ran brake calibration routine, '
              'set min output. Verified with full and empty reel."',
         actual="2025-10-07", logged="2025-12-01T10:20:00Z", cats=["Calibration"], vendors=[202]),
    dict(asset=141, title="Brake pads replaced (M2)",
         desc='Technician: "Brake pads worn to backing plate. Replaced pads, set air gap."',
         actual="2025-03-03", logged="2025-03-04T08:40:00Z", cats=["Mechanical"], vendors=[]),
    dict(asset=112, title="Drive fault on startup (M2)",
         desc='Technician: "Drive faulted on undervoltage at startup. Found loose input terminal, '
              'retorqued all power terminals."',
         actual=None, logged="2024-11-19T12:00:00Z", cats=["Electrical"], vendors=[201]),
    dict(asset=122, title="Take-up reel clamp slipping (M2)",
         desc='Technician: "Reel clamp jaw worn. Replaced jaw inserts."',
         actual="2025-06-17", logged="2025-09-30T15:00:00Z", cats=["Mechanical"], vendors=[]),
    dict(asset=103, title="Line brake slipping – tension low (M3)",
         desc='Technician: "Line #3 losing tension at speed, brake felt loose. Brake air pressure '
              'was 40 psi, spec 60. Replaced leaking regulator, re-ran brake calibration. '
              'Tension stable."',
         actual="2025-12-02", logged="2026-01-15T09:10:00Z", cats=["Mechanical", "Calibration"], vendors=[]),
    dict(asset=113, title="Burnt contactor replaced (M3)",
         desc='Technician: "Main contactor in Line #3 cabinet pitted and discolored, line would '
              'not start. Locked out, replaced contactor, checked coil voltage."',
         actual="2025-04-09", logged="2025-04-10T07:55:00Z", cats=["Electrical"], vendors=[201]),
    dict(asset=113, title="Panel breaker tripping (M3)",
         desc='Technician: "Branch breaker for capstan motor tripping under load. Motor insulation '
              'tested OK. Replaced breaker."',
         actual=None, logged="2026-05-06T14:30:00Z", cats=["Electrical"], vendors=[201]),
    dict(asset=113, title="HMI not communicating with PLC (M3)",
         desc='Technician: "HMI showing System communications fault. Ethernet patch cable damaged '
              'at cabinet door hinge. Replaced and rerouted cable."',
         actual="2026-07-21", logged="2026-07-21T16:00:00Z", cats=["Electrical"], vendors=[]),
    dict(asset=131, title="Capstan belt replaced (M3)",
         desc='Technician: "Capstan drive belt cracked. Replaced belt and tensioned."',
         actual="2025-02-14", logged="2025-05-01T12:00:00Z", cats=["Mechanical"], vendors=[]),
    dict(asset=123, title="Take-up traverse speed drifting (M3)",
         desc='Technician: "Traverse pitch wrong on small reels. Re-entered reel table in HMI."',
         actual=None, logged="2025-10-28T10:00:00Z", cats=["Calibration"], vendors=[]),
    # M4 has a single, unrelated record (an HMI issue).
    dict(asset=114, title="HMI touchscreen unresponsive (M4)",
         desc='Technician: "Touchscreen not registering presses in lower third. Ran touch '
              'calibration from HMI service menu."',
         actual="2026-01-30", logged="2026-03-18T11:45:00Z", cats=["Calibration"], vendors=[]),
]

# Manual pages: (asset_id, attachment_id, file_name, page_number, text).
MANUAL_PAGES = [
    (101, 901, "AL500_Operator_Manual.pdf", 4,
     "SAFETY. Before opening the electrical cabinet or performing any maintenance, the "
     "line must be stopped and locked out at the main disconnect. Verify zero energy at the "
     "drive DC bus before touching any terminal; the DC bus can hold a lethal charge for up "
     "to 5 minutes after power is removed. Only qualified electrical personnel may work "
     "inside the cabinet."),
    (101, 901, "AL500_Operator_Manual.pdf", 31,
     "ALARMS. Code 7 Fault - Network Loss. The drive has lost communication with the "
     "DeviceNet scanner. Check the DeviceNet cable and connectors at the drive and the "
     "cabinet, verify the 121 ohm terminating resistors are present at both ends of the "
     "trunk, and check the scanner card NS (network status) LED. A solid red NS LED "
     "indicates a failed or misconfigured scanner card."),
    (101, 901, "AL500_Operator_Manual.pdf", 32,
     "ALARMS. System communications fault. Raised by the HMI when it cannot reach the line "
     "PLC for more than 2 seconds. On this alarm the line performs a controlled stop: the "
     "capstan ramps down using the standard decel ramp and the brake holds tension until "
     "zero speed. The line cannot be restarted until communications are restored and the "
     "alarm is acknowledged. Check the Ethernet cable between HMI and PLC and the PLC "
     "run status."),
    (101, 901, "AL500_Operator_Manual.pdf", 40,
     "BRAKING RESISTOR. The dynamic braking resistor absorbs regenerative energy during "
     "deceleration. Nominal resistance 18 ohm +/- 5%. A resistor that is discolored, smells "
     "burnt, or measures out of tolerance must be replaced. Repeated overheating usually "
     "indicates a decel ramp set too short for the reel inertia; review drive parameter "
     "P2.14 (decel time) before returning the line to service."),
    (101, 901, "AL500_Operator_Manual.pdf", 46,
     "ARMOR HEAD. The roller plates guide the armor tape onto the cable. Check plate "
     "clearance weekly: 0.5 mm feeler gauge should pass freely between plate and roller. "
     "A rubbing plate shows as a polished stripe on the tape edge."),
    (102, 902, "AL500_Brake_Calibration_Guide.pdf", 2,
     "BRAKE SPECIFICATIONS. Brake controller analog output range: 0 to 10 VDC, corresponding "
     "to 0 to 100% brake torque. Rated brake torque output range 2 to 45 N-m at 60 psi supply "
     "air. Minimum output (P-MIN) should be set so the brake does not grab at thread-up "
     "speed, typically 0.8 to 1.2 VDC."),
    (102, 902, "AL500_Brake_Calibration_Guide.pdf", 3,
     "BRAKE CALIBRATION PROCEDURE. 1. Verify supply air is 60 psi at the brake regulator. "
     "2. With an empty reel, run the line at thread-up speed and adjust P-MIN until tension "
     "reads 5 to 8 lbf. 3. Load a full reel and run at line speed; adjust P-MAX until tension "
     "matches the recipe setpoint. 4. Save parameters and record values on the calibration "
     "log."),
    (103, 903, "AL500_Operator_Manual.pdf", 38,
     "TENSION TROUBLESHOOTING. Low or unstable tension at speed is most often caused by "
     "low brake supply air (spec 60 psi), worn brake pads, or a calibration drift. Check "
     "supply pressure first, then pad thickness (replace below 3 mm), then re-run the brake "
     "calibration procedure."),
    (111, 911, "EC500_Electrical_Schematic.pdf", 7,
     "SHEET 7 - NETWORK. DeviceNet trunk: scanner card slot 3 -> drive node 2 -> HMI node 5. "
     "121 ohm terminating resistors at scanner and HMI ends. 24 VDC network power supplied "
     "from PS2."),
    (113, 913, "EC500_Electrical_Schematic.pdf", 3,
     "SHEET 3 - POWER DISTRIBUTION. Main disconnect Q1 feeds main contactor K1 and branch "
     "breakers F1 (drive), F2 (capstan motor), F3 (control transformer). Capstan motor "
     "branch F2 rated 25 A."),
    (161, 961, "LA140_Installation_Manual.pdf", 12,
     "APPLICATOR. The tamp applicator pad must be adjusted so the label is applied with "
     "3 to 5 mm of pad travel past the product surface. Excess travel causes wrinkled "
     "labels; insufficient travel causes poor adhesion."),
    (161, 962, "Product_Sensor_Operating_Instructions.pdf", 2,
     "TEACH-IN. Hold the teach button for 3 seconds with no product present, then present "
     "product and press again. The yellow LED flashes twice when the teach is accepted."),
]

# Attachments that aren't searchable: an image-only PDF and a photo.
UNSEARCHABLE_ATTACHMENTS = [
    (904, 103, "AL500_Armor_Head_Assembly_Drawing.pdf", "application/pdf", 2),
    (905, 101, "M1_nameplate.jpg", "image/jpeg", 0),
]


def build(path=DEMO_DB_PATH):
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_PATH.read_text())

    conn.executemany("INSERT INTO locations VALUES (?, ?, ?, ?)", LOCATIONS)
    conn.executemany(
        """INSERT INTO assets (id, name, parent_id, location_id, serial_number,
                               manufacturer, model, status, asset_types, extra_fields)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
        ASSETS,
    )
    conn.executemany("INSERT INTO vendors VALUES (?, ?, ?, ?, ?)", VENDORS)

    asset_location = {a[0]: a[3] for a in ASSETS}
    for seq, wo in enumerate(WORK_ORDERS, start=1):
        wo_id = 5000 + seq
        extra = '{"Actual Completion Date": "%s"}' % wo["actual"] if wo["actual"] else "{}"
        conn.execute(
            """INSERT INTO work_orders
                 (id, sequential_id, title, description, asset_id, location_id, status, type,
                  priority, created_at, completed_at, updated_at, extra_fields, actual_completion_date)
               VALUES (?, ?, ?, ?, ?, ?, 'DONE', 'REACTIVE', 'MEDIUM', ?, ?, ?, ?, ?)""",
            (wo_id, seq, wo["title"], wo["desc"], wo["asset"], asset_location[wo["asset"]],
             wo["logged"], wo["logged"], wo["logged"], extra, wo["actual"]),
        )
        conn.executemany(
            "INSERT INTO work_order_categories VALUES (?, ?)",
            [(wo_id, c) for c in wo["cats"]],
        )
        conn.executemany(
            "INSERT INTO work_order_vendors VALUES (?, ?)",
            [(wo_id, v) for v in wo["vendors"]],
        )
        conn.execute(
            "INSERT INTO attachments VALUES (?, ?, ?, 'application/pdf')",
            (7000 + seq, wo_id, f"invoice_{10400 + seq}.pdf"),
        )

    indexed = {}
    for asset_id, att_id, file_name, page, text in MANUAL_PAGES:
        conn.execute(
            """INSERT INTO manual_chunks (chunk_text, asset_id, attachment_id, file_name, page_number)
               VALUES (?, ?, ?, ?, ?)""",
            (text, asset_id, att_id, file_name, page),
        )
        indexed[att_id] = (asset_id, file_name)
    conn.executemany(
        "INSERT INTO asset_attachments VALUES (?, ?, ?, 'application/pdf', NULL, 1)",
        [(att_id, asset_id, name) for att_id, (asset_id, name) in indexed.items()],
    )
    conn.executemany(
        "INSERT INTO asset_attachments VALUES (?, ?, ?, ?, NULL, ?)",
        UNSEARCHABLE_ATTACHMENTS,
    )

    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    out = build()
    print(f"Wrote fictional demo dataset to {out}")
