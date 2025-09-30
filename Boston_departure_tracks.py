# Build flight-track lines + departure tracks from CSV (ArcGIS Pro / ArcPy)
# Author: My Nguyen
# Date: 2025-09-19

import arcpy, csv, os, datetime, sys

# ========= EDIT THESE =========
ROOT = r"C:\Users\mnguyen\Downloads\Prof Bradley"
CSV_PATH = os.path.join(ROOT, "Boston_departure_last_28_days.csv")     # your CSV
GDB_PATH = os.path.join(ROOT, "boston_dep_last_28_days.gdb")
SPREF = arcpy.SpatialReference(4326)                # WGS 1984
MAKE_SMOOTH = True                                  # set False to skip smoothing
SMOOTH_TOL_M = 200                                  # PAEK tolerance in meters
BOS_LON, BOS_LAT = -71.00956, 42.36561              # Logan approx center
BOS_BUF_M = int(3 * 1852)                           # 3 nm (meters)
ENFORCE_DEP_BOS = True                              # use dep_aprt == 'BOS' if column exists
DEP_APRT_CODE = "BOS"
# ==============================

arcpy.env.overwriteOutput = True

# -------- New: create an export subfolder under ROOT --------
csv_base = os.path.splitext(os.path.basename(CSV_PATH))[0]
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_SHP_DIR = os.path.join(ROOT, f"shapefiles_{csv_base}_{timestamp}")
os.makedirs(OUT_SHP_DIR, exist_ok=True)
print(f"Shapefiles will be written to: {OUT_SHP_DIR}")
# ------------------------------------------------------------

# -- workspace
if not arcpy.Exists(GDB_PATH):
    arcpy.management.CreateFileGDB(os.path.dirname(GDB_PATH), os.path.basename(GDB_PATH))
arcpy.env.workspace = GDB_PATH

# Names
pts_fc = "flights_pts"
pts_sorted = "flights_pts_sorted"
lines_fc = "flights_tracks"
lines_smooth = "flights_tracks_smooth"
bos_pt = "bos_center"
bos_buf = "bos_3nmi"
start_pts = "tracks_start_pts"
end_pts   = "tracks_end_pts"
arrivals_fc = "tracks_arrivals"
departs_fc  = "tracks_departures"

# Clean any leftovers for idempotency
for fc in [pts_fc, pts_sorted, lines_fc, lines_smooth, bos_pt, bos_buf, start_pts, end_pts, arrivals_fc, departs_fc]:
    if arcpy.Exists(fc):
        arcpy.management.Delete(fc)

# 1) Create empty point FC (WGS84) with fields
arcpy.management.CreateFeatureclass(GDB_PATH, pts_fc, "POINT", spatial_reference=SPREF)
for name, ftype, flen in [
    ("flight_id", "TEXT", 64),
    ("ts", "DATE", None),
    ("lat", "DOUBLE", None),
    ("lon", "DOUBLE", None),
]:
    arcpy.management.AddField(pts_fc, name, ftype, field_length=flen)

# --- helpers ---
def parse_dt(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace('Z','').replace('z',''))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def resolve_column(cols_lower_map, *candidates):
    """
    Given a dict {lowername: actualname}, return the actual header that matches
    the first existing candidate (case-insensitive). Raises KeyError if none.
    """
    for cand in candidates:
        lc = cand.lower()
        if lc in cols_lower_map:
            return cols_lower_map[lc]
    raise KeyError("/".join(candidates))

# 2) Load CSV → points (auto-detect lat/lon headers; optional dep_aprt filter)
fields = ("flight_id", "ts", "lat", "lon", "SHAPE@XY")
inserted = 0
skipped = 0

with open(CSV_PATH, encoding="utf-8-sig", newline="") as f, arcpy.da.InsertCursor(pts_fc, fields) as icur:
    rdr = csv.DictReader(f)
    if not rdr.fieldnames:
        raise RuntimeError("CSV has no header row.")

    # Build case-insensitive header mapping
    cols_map = {h.lower(): h for h in rdr.fieldnames}

    # Resolve required columns
    flight_col = resolve_column(cols_map, "flight_index", "flight_id", "flight")
    date_col   = resolve_column(cols_map, "date", "timestamp", "ts", "time")
    lat_col    = resolve_column(cols_map, "lat", "latitude", "y", "lat_dd")
    lon_col    = resolve_column(cols_map, "long", "longitude", "lon", "x", "lon_dd")

    # Optional dep_aprt column
    dep_col = cols_map.get("dep_aprt")

    print("Resolved columns:",
          f"flight={flight_col}, date={date_col}, lat={lat_col}, lon={lon_col}",
          f"dep_aprt={dep_col}" if dep_col else "(dep_aprt not present)")

    for r in rdr:
        try:
            if ENFORCE_DEP_BOS and dep_col:
                if (r.get(dep_col) or "").strip().upper() != DEP_APRT_CODE:
                    continue  # skip non-BOS departures if any slipped in

            fid = str(r[flight_col]).strip()
            t   = parse_dt(r[date_col])
            lat_raw = (r.get(lat_col) or "").strip()
            lon_raw = (r.get(lon_col) or "").strip()
            if not lat_raw or not lon_raw:
                raise ValueError("blank lat/lon")
            lat = float(lat_raw)
            lon = float(lon_raw)
            icur.insertRow((fid, t, lat, lon, (lon, lat)))
            inserted += 1
        except Exception as e:
            skipped += 1
            if skipped <= 10 or skipped % 5000 == 0:
                print(f"Skip row ({skipped}): {e}")

print(f"Loaded {inserted} points into {pts_fc}. Skipped {skipped} rows.")
if inserted == 0:
    raise RuntimeError("No points were loaded. Check your column mappings and data values.")

# 3) Sort by flight_id then time
arcpy.management.Sort(pts_fc, pts_sorted, [["flight_id", "ASCENDING"], ["ts", "ASCENDING"]])

# 4) Points → Lines (tracks)
arcpy.management.PointsToLine(pts_sorted, lines_fc, "flight_id", "ts", "NO_CLOSE")
if "flight_id" not in [f.name for f in arcpy.ListFields(lines_fc)]:
    arcpy.management.AddField(lines_fc, "flight_id", "TEXT", field_length=64)

# 5) Optional smoothing
lines_for_class = lines_fc
if MAKE_SMOOTH:
    arcpy.cartography.SmoothLine(lines_fc, lines_smooth, "PAEK", f"{SMOOTH_TOL_M} Meters",
                                 "FIXED_CLOSED_ENDPOINT", "NO_CHECK")
    lines_for_class = lines_smooth

# 6) BOS center + geodesic 3 nmi buffer
arcpy.management.CreateFeatureclass(GDB_PATH, bos_pt, "POINT", spatial_reference=SPREF)
with arcpy.da.InsertCursor(bos_pt, ["SHAPE@XY"]) as ic:
    ic.insertRow(((BOS_LON, BOS_LAT),))
arcpy.analysis.Buffer(bos_pt, bos_buf, f"{BOS_BUF_M} Meters", dissolve_option="ALL", method="GEODESIC")

# 7) Start/End points per track
for out_name, ptype in [(start_pts, "START"), (end_pts, "END")]:
    arcpy.management.FeatureVerticesToPoints(lines_for_class, out_name, ptype)

# 8) Flag which start/end points are within the BOS buffer
for fc, flag_field in [(start_pts, "near_start"), (end_pts, "near_end")]:
    if flag_field not in [f.name for f in arcpy.ListFields(fc)]:
        arcpy.management.AddField(fc, flag_field, "SHORT")
        arcpy.management.CalculateField(fc, flag_field, 0, "PYTHON3")
    lyr = arcpy.management.MakeFeatureLayer(fc, f"{fc}_lyr").getOutput(0)
    arcpy.management.SelectLayerByLocation(lyr, "INTERSECT", bos_buf)
    arcpy.management.CalculateField(lyr, flag_field, 1, "PYTHON3")
    arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
    arcpy.management.Delete(lyr)

# 9) Join flags back to tracks (by flight_id)
for child_fc, fld in [(start_pts, "near_start"), (end_pts, "near_end")]:
    arcpy.management.JoinField(lines_for_class, "flight_id", child_fc, "flight_id", [fld])

# Ensure defaults
for fld in ("near_start", "near_end"):
    if fld not in [f.name for f in arcpy.ListFields(lines_for_class)]:
        arcpy.management.AddField(lines_for_class, fld, "SHORT")
        arcpy.management.CalculateField(lines_for_class, fld, 0, "PYTHON3")
    else:
        arcpy.management.CalculateField(lines_for_class, fld, f"0 if !{fld}! is None else !{fld}!", "PYTHON3")

# 10) Classify phase
if "phase" not in [f.name for f in arcpy.ListFields(lines_for_class)]:
    arcpy.management.AddField(lines_for_class, "phase", "TEXT", field_length=16)

codeblock = """
def phase(ns, ne):
    ns = 0 if ns is None else ns
    ne = 0 if ne is None else ne
    if ns == 1 and ne != 1:
        return "Departure"
    elif ne == 1 and ns != 1:
        return "Arrival"
    elif ns == 1 and ne == 1:
        return "Local"
    else:
        return "Overflight"
"""
arcpy.management.CalculateField(lines_for_class, "phase",
                                "phase(!near_start!, !near_end!)", "PYTHON3", codeblock)

# 11) Split to separate FCs
for val, out_fc in [("Arrival", arrivals_fc), ("Departure", departs_fc)]:
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    arcpy.analysis.Select(lines_for_class, out_fc, f"phase = '{val}'")

# -------- Changed: export shapefiles into the new OUT_SHP_DIR --------
for fc in [pts_fc, lines_for_class, departs_fc, bos_buf]:
    arcpy.conversion.FeatureClassToShapefile([fc], OUT_SHP_DIR)

print("Done.")
print(f"- Points: {pts_fc}")
print(f"- Tracks: {lines_for_class}")
print(f"- BOS buffer: {bos_buf}")
print(f"- Departures: {departs_fc}")
print(f"Shapefiles written to: {OUT_SHP_DIR}")
