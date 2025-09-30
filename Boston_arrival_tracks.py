# Build flight-track lines + arrival tracks from CSV (ArcGIS Pro / ArcPy)
# Author: My Nguyen
# Date: 2025-09-19

import arcpy, csv, os, datetime

# ========= EDIT THESE =========
ROOT = r"C:\Users\mnguyen\Downloads\Prof Bradley"
CSV_PATH = os.path.join(ROOT, "Boston_arrival_first_28_days.csv")
GDB_PATH = os.path.join(ROOT, "boston_flights.gdb")
SPREF = arcpy.SpatialReference(4326)  # WGS 1984
MAKE_SMOOTH = True                    # set False to skip smoothing
SMOOTH_TOL_M = 200                    # PAEK tolerance in meters
BOS_LON, BOS_LAT = -71.00956, 42.36561  # Logan approximate center
BOS_BUF_M = int(3 * 1852)             # 3 nautical miles in meters (~5556 m)
# ==============================

arcpy.env.overwriteOutput = True

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
tracks_w_phase = "flights_tracks_phase"
arrivals_fc = "tracks_arrivals"
departs_fc  = "tracks_departures"

# 1) Create empty point FC (WGS84) with fields
if arcpy.Exists(pts_fc):
    arcpy.management.Delete(pts_fc)

arcpy.management.CreateFeatureclass(GDB_PATH, pts_fc, "POINT", spatial_reference=SPREF)
arcpy.management.AddField(pts_fc, "flight_id", "TEXT", field_length=64)
arcpy.management.AddField(pts_fc, "ts", "DATE")
arcpy.management.AddField(pts_fc, "lat", "DOUBLE")
arcpy.management.AddField(pts_fc, "lon", "DOUBLE")

# robust datetime parser
def parse_dt(s):
    if s is None: return None
    s = s.strip()
    if not s: return None
    try:
        # ISO 8601 (with or without 'T' / 'Z')
        return datetime.datetime.fromisoformat(s.replace('Z','').replace('z',''))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    # last resort: just date
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

# 2) Load CSV → points
fields = ("flight_id", "ts", "lat", "lon", "SHAPE@XY")
inserted = 0
with arcpy.da.InsertCursor(pts_fc, fields) as icur, open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
    rdr = csv.DictReader(f)
    for r in rdr:
        try:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
            fid = str(r["flight_index"])
            t   = parse_dt(r["date"])
            icur.insertRow((fid, t, lat, lon, (lon, lat)))
            inserted += 1
        except Exception as e:
            # skip bad rows
            print(f"Skip row: {e}")

print(f"Loaded {inserted} points into {pts_fc}")

# 3) Sort by flight_id then time
if arcpy.Exists(pts_sorted):
    arcpy.management.Delete(pts_sorted)
arcpy.management.Sort(pts_fc, pts_sorted, [["flight_id", "ASCENDING"], ["ts", "ASCENDING"]])

# 4) Points → Lines (tracks)
if arcpy.Exists(lines_fc):
    arcpy.management.Delete(lines_fc)
arcpy.management.PointsToLine(pts_sorted, lines_fc, "flight_id", "ts", "NO_CLOSE")
arcpy.management.AddField(lines_fc, "flight_id", "TEXT", field_length=64)  # ensure exists post-tool
# (PointsToLine carries fields, but making sure flight_id is present)

# 5) Optional smoothing for aesthetics
if MAKE_SMOOTH:
    if arcpy.Exists(lines_smooth):
        arcpy.management.Delete(lines_smooth)
    arcpy.cartography.SmoothLine(lines_fc, lines_smooth, "PAEK", f"{SMOOTH_TOL_M} Meters", "FIXED_CLOSED_ENDPOINT", "NO_CHECK")
    lines_for_class = lines_smooth
else:
    lines_for_class = lines_fc

# 6) Logan center + geodesic 3 nmi buffer
if arcpy.Exists(bos_pt):
    arcpy.management.Delete(bos_pt)
arcpy.management.CreateFeatureclass(GDB_PATH, bos_pt, "POINT", spatial_reference=SPREF)
with arcpy.da.InsertCursor(bos_pt, ["SHAPE@XY"]) as ic:
    ic.insertRow(((BOS_LON, BOS_LAT),))

if arcpy.Exists(bos_buf):
    arcpy.management.Delete(bos_buf)
# GEODESIC buffer to keep distance correct
arcpy.analysis.Buffer(bos_pt, bos_buf, f"{BOS_BUF_M} Meters", dissolve_option="ALL", method="GEODESIC")

# 7) Start/End points of each track
for out_name, ptype in [(start_pts, "START"), (end_pts, "END")]:
    if arcpy.Exists(out_name):
        arcpy.management.Delete(out_name)
    arcpy.management.FeatureVerticesToPoints(lines_for_class, out_name, ptype)

# 8) Flag which start/end points are within the airport buffer
for fc, flag_field in [(start_pts, "near_start"), (end_pts, "near_end")]:
    if flag_field not in [f.name for f in arcpy.ListFields(fc)]:
        arcpy.management.AddField(fc, flag_field, "SHORT")
        arcpy.management.CalculateField(fc, flag_field, 0, "PYTHON3")
    # select points that intersect buffer
    lyr = arcpy.management.MakeFeatureLayer(fc, f"{fc}_lyr").getOutput(0)
    arcpy.management.SelectLayerByLocation(lyr, "INTERSECT", bos_buf)
    arcpy.management.CalculateField(lyr, flag_field, 1, "PYTHON3")
    arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
    arcpy.management.Delete(lyr)

# 9) Join flags back to tracks (by flight_id)
for child_fc, fld in [(start_pts, "near_start"), (end_pts, "near_end")]:
    arcpy.management.JoinField(lines_for_class, "flight_id", child_fc, "flight_id", [fld])

# Ensure the two flag fields exist (default 0 if null)
for fld in ("near_start", "near_end"):
    if fld not in [f.name for f in arcpy.ListFields(lines_for_class)]:
        arcpy.management.AddField(lines_for_class, fld, "SHORT")
        arcpy.management.CalculateField(lines_for_class, fld, 0, "PYTHON3")
    else:
        # replace nulls with 0
        arcpy.management.CalculateField(lines_for_class, fld,
            "0 if !{}! is None else !{}!".format(fld, fld), "PYTHON3")

# 10) Classify Arrival / Departure / Overflight
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
                                "phase(!near_start!, !near_end!)",
                                "PYTHON3", codeblock)

# 11) Split into separate feature classes + (optional) shapefiles
for val, out_fc in [("Arrival", arrivals_fc), ("Departure", departs_fc)]:
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    where = f"phase = '{val}'"
    arcpy.analysis.Select(lines_for_class, out_fc, where)

# Also export shapefiles for convenience
out_shp_dir = ROOT
for fc in [pts_fc, lines_for_class, arrivals_fc, departs_fc, bos_buf]:
    shp = os.path.join(out_shp_dir, f"{fc}.shp")
    if arcpy.Exists(shp):
        arcpy.management.Delete(shp)
    arcpy.conversion.FeatureClassToShapefile([fc], out_shp_dir)

print("Done.")
print(f"- Points: {pts_fc}")
print(f"- Tracks: {lines_for_class}")
print(f"- BOS buffer: {bos_buf}")
print(f"- Arrivals: {arrivals_fc}, Departures: {departs_fc}")
print(f"Shapefiles also written to: {ROOT}")
