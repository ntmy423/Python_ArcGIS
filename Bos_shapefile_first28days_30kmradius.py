# Build flight-track lines from CSV with dist_to_BOS <= 30 km (ArcGIS Pro / ArcPy)
# Author: My Nguyen
# Date: 2025-10-19  (updated for no dep/arr columns)

import arcpy, csv, os, datetime

# ========= EDIT THESE =========
ROOT = r"C:\Users\mnguyen\Downloads\Prof Bradley\Boston_2"
CSV_PATH = os.path.join(ROOT, "Boston_first28days_30kmradius.csv")
GDB_PATH = os.path.join(ROOT, "boston_first28days_30kmradius.gdb")
SPREF = arcpy.SpatialReference(4326)   # WGS 1984
MAKE_SMOOTH = True                     # set False to skip smoothing
SMOOTH_TOL_M = 200                     # PAEK tolerance in meters
MAX_DIST_KM = 60.0                     # keep rows with dist_to_BOS <= 30 km
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

# 2) Load CSV → points (keep only dist_to_BOS <= 30 km)
fields = ("flight_id", "ts", "lat", "lon", "dist_km", "SHAPE@XY")
inserted = 0
skipped = 0
skipped_far = 0

with open(CSV_PATH, encoding="utf-8-sig", newline="") as f, arcpy.da.InsertCursor(pts_fc, fields) as icur:
    rdr = csv.DictReader(f)
    if not rdr.fieldnames:
        raise RuntimeError("CSV has no header row.")

    cols_map = {h.lower(): h for h in rdr.fieldnames}

    flight_col = resolve_column(cols_map, "flight_index", "flight_id", "flight")
    date_col   = resolve_column(cols_map, "date", "timestamp", "ts", "time")
    lat_col    = resolve_column(cols_map, "lat", "latitude", "y", "lat_dd")
    lon_col    = resolve_column(cols_map, "long", "longitude", "lon", "x", "lon_dd")
    dist_col   = resolve_column(cols_map, "dist_to_bos", "dist_km", "distance_km", "dist_to_bos_km")

    print("Resolved columns:",
          f"flight={flight_col}, date={date_col}, lat={lat_col}, lon={lon_col}, dist_km={dist_col}")

    for r in rdr:
        try:
            dist_raw = (r.get(dist_col) or "").strip()
            if not dist_raw:
                raise ValueError("blank dist_to_BOS")
            dist_km = float(dist_raw)
            if dist_km > MAX_DIST_KM:
                skipped_far += 1
                continue

            fid = str(r[flight_col]).strip()
            t   = parse_dt(r[date_col])
            lat_raw = (r.get(lat_col) or "").strip()
            lon_raw = (r.get(lon_col) or "").strip()
            if not lat_raw or not lon_raw:
                raise ValueError("blank lat/lon")
            lat = float(lat_raw)
            lon = float(lon_raw)

            icur.insertRow((fid, t, lat, lon, dist_km, (lon, lat)))
            inserted += 1
        except Exception as e:
            skipped += 1
            if skipped <= 10 or skipped % 5000 == 0:
                print(f"Skip row ({skipped}): {e}")

print(f"Loaded {inserted} points into {pts_fc}. Skipped {skipped} invalid rows, {skipped_far} with dist_to_BOS > {MAX_DIST_KM} km.")
if inserted == 0:
    raise RuntimeError("No points were loaded after filtering. Check mappings and distance values.")

# 3) Sort by flight_id then time
arcpy.management.Sort(pts_fc, pts_sorted, [["flight_id", "ASCENDING"], ["ts", "ASCENDING"]])

# 4) Points → Lines (tracks)
arcpy.management.PointsToLine(pts_sorted, lines_fc, "flight_id", "ts", "NO_CLOSE")
if "flight_id" not in [f.name for f in arcpy.ListFields(lines_fc)]:
    arcpy.management.AddField(lines_fc, "flight_id", "TEXT", field_length=64)

# 5) Optional smoothing
lines_for_output = lines_fc
if MAKE_SMOOTH:
    arcpy.cartography.SmoothLine(lines_fc, lines_smooth, "PAEK", f"{SMOOTH_TOL_M} Meters",
                                 "FIXED_CLOSED_ENDPOINT", "NO_CHECK")
    lines_for_output = lines_smooth

# 6) Export tracks shapefile only
arcpy.conversion.FeatureClassToShapefile([lines_for_output], OUT_SHP_DIR)

print("Done.")
print(f"- Tracks (dist_to_BOS <= {MAX_DIST_KM} km): {lines_for_output}")
print(f"Shapefile folder: {OUT_SHP_DIR}")
