# Build flight-track lines from CSV with <= 60 km of OAK/SFO/SJC/SMF
# and altitudex100ft <= 50 (<= 5,000 ft) (ArcGIS Pro / ArcPy)
# Author: My Nguyen
# Date: 2025-10-28  (NorCal multi-airport + altitude filter)

import arcpy, csv, os, datetime

# ========= EDIT THESE =========
ROOT = r"C:\Users\mnguyen\Downloads\Prof Bradley\NorCal\05mar2015"
CSV_PATH = os.path.join(ROOT, "NorCal_05mar2015_first28days.csv")
GDB_PATH = os.path.join(ROOT, "norcal_05mar2015_first28days.gdb")
SPREF = arcpy.SpatialReference(4326)   # WGS 1984
MAKE_SMOOTH = True                     # set False to skip smoothing
SMOOTH_TOL_M = 200                     # PAEK tolerance in meters
MAX_DIST_KM = 60.0                     # keep rows with distance to airport <= 60 km
MAX_ALT_100FT = 50.0                   # keep rows with altitudex100ft <= 50 (<= 5,000 ft)
AIRPORT_CODES = ["OAK", "SFO", "SJC", "SMF"]
# ==============================

arcpy.env.overwriteOutput = True

# Output folder for shapefiles
csv_base = os.path.splitext(os.path.basename(CSV_PATH))[0]
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_SHP_DIR = os.path.join(ROOT, f"shapefiles_{csv_base}_{timestamp}")
os.makedirs(OUT_SHP_DIR, exist_ok=True)
print(f"Shapefiles will be written to: {OUT_SHP_DIR}")

# Workspace
if not arcpy.Exists(GDB_PATH):
    arcpy.management.CreateFileGDB(os.path.dirname(GDB_PATH), os.path.basename(GDB_PATH))
arcpy.env.workspace = GDB_PATH

# Helpers
import datetime as _dt

def parse_dt(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace('Z','').replace('z',''))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def resolve_column(cols_lower_map, *candidates):
    for cand in candidates:
        lc = cand.lower()
        if lc in cols_lower_map:
            return cols_lower_map[lc]
    raise KeyError("/".join(candidates))

# First pass: sniff headers
with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
    rdr = csv.DictReader(f)
    if not rdr.fieldnames:
        raise RuntimeError("CSV has no header row.")
    COLS_MAP = {h.lower(): h for h in rdr.fieldnames}

# Resolve shared columns
flight_col = resolve_column(COLS_MAP, "flight_index", "flight_id", "flight")
date_col   = resolve_column(COLS_MAP, "date", "timestamp", "ts", "time")
lat_col    = resolve_column(COLS_MAP, "lat", "latitude", "y", "lat_dd")
lon_col    = resolve_column(COLS_MAP, "long", "longitude", "lon", "x", "lon_dd")

# Altitude column variants (values are in 100 ft units)
alt_col    = resolve_column(
    COLS_MAP,
    "altitudex100ft", "altitude_x100ft", "altitude100ft", "altitude_100ft",
    "altitude_x100_ft", "alt100ft", "alt_100ft"
)

# Per-airport distance column candidates, including the 'dis_to_*' variant
DIST_CANDIDATES = {
    "OAK": ["dis_to_oak", "dist_to_oak", "oak_km", "dist_oak_km", "distance_to_oak_km", "distance_to_oak", "dist_oak"],
    "SFO": ["dis_to_sfo", "dist_to_sfo", "sfo_km", "dist_sfo_km", "distance_to_sfo_km", "distance_to_sfo", "dist_sfo"],
    "SJC": ["dis_to_sjc", "dist_to_sjc", "sjc_km", "dist_sjc_km", "distance_to_sjc_km", "distance_to_sjc", "dist_sjc"],
    "SMF": ["dis_to_smf", "dist_to_smf", "smf_km", "dist_smf_km", "distance_to_smf_km", "distance_to_smf", "dist_smf"],
}

resolved_dist_cols = {}
for code in AIRPORT_CODES:
    for cand in DIST_CANDIDATES[code]:
        if cand.lower() in COLS_MAP:
            resolved_dist_cols[code] = COLS_MAP[cand.lower()]
            break
    if code not in resolved_dist_cols:
        print(f"Warning: No distance column found for {code}. Checked: {DIST_CANDIDATES[code]}")

print("Resolved shared columns:",
      f"flight={flight_col}, date={date_col}, lat={lat_col}, lon={lon_col}, alt_100ft={alt_col}")
for code in AIRPORT_CODES:
    print(f"{code} distance column:", resolved_dist_cols.get(code, "NOT FOUND"))

def process_airport(code):
    if code not in resolved_dist_cols:
        print(f"Skip {code}: distance column not found.")
        return None

    dist_col = resolved_dist_cols[code]

    # Unique names per airport
    pts_fc = f"flights_pts_{code}"
    pts_sorted = f"flights_pts_sorted_{code}"
    lines_fc = f"flights_tracks_{code}"
    lines_smooth = f"flights_tracks_smooth_{code}"

    # Clean leftovers
    for fc in [pts_fc, pts_sorted, lines_fc, lines_smooth]:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)

    # 1) Create empty point FC
    arcpy.management.CreateFeatureclass(GDB_PATH, pts_fc, "POINT", spatial_reference=SPREF)
    for name, ftype, flen in [
        ("flight_id", "TEXT", 64),
        ("ts", "DATE", None),
        ("lat", "DOUBLE", None),
        ("lon", "DOUBLE", None),
        (f"dist_{code}_km", "DOUBLE", None),
        ("alt_100ft", "DOUBLE", None),
    ]:
        arcpy.management.AddField(pts_fc, name, ftype, field_length=flen)

    # 2) Load CSV → points, apply both filters
    fields = ("flight_id", "ts", "lat", "lon", f"dist_{code}_km", "alt_100ft", "SHAPE@XY")
    inserted = 0
    skipped = 0
    skipped_far = 0
    skipped_high_alt = 0

    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f, arcpy.da.InsertCursor(pts_fc, fields) as icur:
        rdr = csv.DictReader(f)
        for r in rdr:
            try:
                # Distance filter for this airport
                dist_raw = (r.get(dist_col) or "").strip()
                if not dist_raw:
                    raise ValueError(f"blank {dist_col}")
                dist_km = float(dist_raw)
                if dist_km > MAX_DIST_KM:
                    skipped_far += 1
                    continue

                # Altitude filter (values are in 100 ft units)
                alt_raw = (r.get(alt_col) or "").strip()
                if alt_raw == "":
                    raise ValueError("blank altitudex100ft")
                alt_100ft_val = float(alt_raw)
                if alt_100ft_val > MAX_ALT_100FT:
                    skipped_high_alt += 1
                    continue

                # Basics
                fid = str(r[flight_col]).strip()
                t   = parse_dt(r[date_col])
                lat_raw = (r.get(lat_col) or "").strip()
                lon_raw = (r.get(lon_col) or "").strip()
                if not lat_raw or not lon_raw:
                    raise ValueError("blank lat/lon")
                lat = float(lat_raw)
                lon = float(lon_raw)

                icur.insertRow((fid, t, lat, lon, dist_km, alt_100ft_val, (lon, lat)))
                inserted += 1
            except Exception as e:
                skipped += 1
                if skipped <= 10 or skipped % 5000 == 0:
                    print(f"[{code}] Skip row ({skipped}): {e}")

    print(
        f"[{code}] Loaded {inserted} points into {pts_fc}. "
        f"Skipped {skipped} invalid rows, "
        f"{skipped_far} with {dist_col} > {MAX_DIST_KM} km, "
        f"{skipped_high_alt} with altitudex100ft > {MAX_ALT_100FT}."
    )
    if inserted == 0:
        print(f"[{code}] No points loaded. Skipping track creation.")
        return None

    # 3) Sort by flight_id then time
    arcpy.management.Sort(pts_fc, pts_sorted, [["flight_id", "ASCENDING"], ["ts", "ASCENDING"]])

    # 4) Points → Lines (tracks)
    arcpy.management.PointsToLine(pts_sorted, lines_fc, "flight_id", "ts", "NO_CLOSE")
    if "flight_id" not in [f.name for f in arcpy.ListFields(lines_fc)]:
        arcpy.management.AddField(lines_fc, "flight_id", "TEXT", field_length=64)

    # 5) Optional smoothing
    lines_for_output = lines_fc
    if MAKE_SMOOTH:
        arcpy.cartography.SmoothLine(
            lines_fc, lines_smooth, "PAEK", f"{SMOOTH_TOL_M} Meters",
            "FIXED_CLOSED_ENDPOINT", "NO_CHECK"
        )
        lines_for_output = lines_smooth

    # 6) Export tracks shapefile
    arcpy.conversion.FeatureClassToShapefile([lines_for_output], OUT_SHP_DIR)

    print(f"[{code}] Done.")
    print(f"[{code}] Tracks (<= {MAX_DIST_KM} km & altitudex100ft <= {MAX_ALT_100FT}): {lines_for_output}")
    print(f"[{code}] Shapefile folder: {OUT_SHP_DIR}")
    return lines_for_output

# Run for each airport
for code in AIRPORT_CODES:
    process_airport(code)
