# Build flight-track lines from CSV with dist_to_SEA <= 60 km and altitudex100ft <= 5000ft (ArcGIS Pro / ArcPy)
# Author: My Nguyen
# Date: 2025-10-19  (updated for no dep/arr columns + altitude filter)

import arcpy, csv, os, datetime

# ========= EDIT THESE =========
ROOT = r"C:\Users\mnguyen\Downloads\Prof Bradley\Seattle"
CSV_PATH = os.path.join(ROOT, "Seattle_first28days.csv")
GDB_PATH = os.path.join(ROOT, "seattle_first28days.gdb")
SPREF = arcpy.SpatialReference(4326)   # WGS 1984
MAKE_SMOOTH = True                     # set False to skip smoothing
SMOOTH_TOL_M = 200                     # PAEK tolerance in meters
MAX_DIST_KM = 60.0                     # keep rows with dist_to_SEA <= 60 km
MAX_ALT_100FT = 50.0                   # keep rows with altitudex100ft <= 50 (<= 5,000 ft)
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

# Names
pts_fc = "flights_pts"
pts_sorted = "flights_pts_sorted"
lines_fc = "flights_tracks"
lines_smooth = "flights_tracks_smooth"

# Clean leftovers
for fc in [pts_fc, pts_sorted, lines_fc, lines_smooth]:
    if arcpy.Exists(fc):
        arcpy.management.Delete(fc)

# 1) Empty point FC (WGS84) with fields
arcpy.management.CreateFeatureclass(GDB_PATH, pts_fc, "POINT", spatial_reference=SPREF)
for name, ftype, flen in [
    ("flight_id", "TEXT", 64),
    ("ts", "DATE", None),
    ("lat", "DOUBLE", None),
    ("lon", "DOUBLE", None),
    ("dist_km", "DOUBLE", None),
    ("alt_100ft", "DOUBLE", None),   # store altitude (x100 ft)
]:
    arcpy.management.AddField(pts_fc, name, ftype, field_length=flen)

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

# 2) Load CSV → points (keep only dist_to_SEA <= 60 km and altitudex100ft <= 50)
fields = ("flight_id", "ts", "lat", "lon", "dist_km", "alt_100ft", "SHAPE@XY")
inserted = 0
skipped = 0
skipped_far = 0
skipped_high_alt = 0

with open(CSV_PATH, encoding="utf-8-sig", newline="") as f, arcpy.da.InsertCursor(pts_fc, fields) as icur:
    rdr = csv.DictReader(f)
    if not rdr.fieldnames:
        raise RuntimeError("CSV has no header row.")

    cols_map = {h.lower(): h for h in rdr.fieldnames}

    flight_col = resolve_column(cols_map, "flight_index", "flight_id", "flight")
    date_col   = resolve_column(cols_map, "date", "timestamp", "ts", "time")
    lat_col    = resolve_column(cols_map, "lat", "latitude", "y", "lat_dd")
    lon_col    = resolve_column(cols_map, "long", "longitude", "lon", "x", "lon_dd")
    dist_col   = resolve_column(cols_map, "dist_to_sea", "dist_km", "distance_km", "dist_to_sea_km")
    # Accept several naming variants for altitude column
    alt_col    = resolve_column(
                    cols_map,
                    "altitudex100ft", "altitude_x100ft", "altitude100ft", "altitude_100ft",
                    "altitude_x100_ft", "alt100ft", "alt_100ft"
                 )

    print("Resolved columns:",
          f"flight={flight_col}, date={date_col}, lat={lat_col}, lon={lon_col}, dist_km={dist_col}, alt_100ft={alt_col}")

    for r in rdr:
        try:
            # Distance filter
            dist_raw = (r.get(dist_col) or "").strip()
            if not dist_raw:
                raise ValueError("blank dist_to_SEA")
            dist_km = float(dist_raw)
            if dist_km > MAX_DIST_KM:
                skipped_far += 1
                continue

            # Altitude filter (values are in 100 ft units)
            alt_raw = (r.get(alt_col) or "").strip()
            if alt_raw == "":
                raise ValueError("blank altitudex100ft")
            alt_100ft = float(alt_raw)
            if alt_100ft > MAX_ALT_100FT:
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

            icur.insertRow((fid, t, lat, lon, dist_km, alt_100ft, (lon, lat)))
            inserted += 1
        except Exception as e:
            skipped += 1
            if skipped <= 10 or skipped % 5000 == 0:
                print(f"Skip row ({skipped}): {e}")

print(
    f"Loaded {inserted} points into {pts_fc}. "
    f"Skipped {skipped} invalid rows, "
    f"{skipped_far} with dist_to_SEA > {MAX_DIST_KM} km, "
    f"{skipped_high_alt} with altitudex100ft > {MAX_ALT_100FT}."
)
if inserted == 0:
    raise RuntimeError("No points were loaded after filtering. Check mappings and distance/altitude values.")

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

# 6) Export tracks shapefile only
arcpy.conversion.FeatureClassToShapefile([lines_for_output], OUT_SHP_DIR)

print("Done.")
print(f"- Tracks (dist_to_SEA <= {MAX_DIST_KM} km & altitudex100ft <= {MAX_ALT_100FT}): {lines_for_output}")
print(f"Shapefile folder: {OUT_SHP_DIR}")
