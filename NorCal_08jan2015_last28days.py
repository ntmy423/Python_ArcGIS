import pandas as pd
import re

# --- params ---
DAYS = 28  # number of calendar days to keep, inclusive of the latest day

# --- paths ---
in_csv  = r"C:\Users\mnguyen\Downloads\Prof Bradley\NorCal\08jan2015\IFR_MetroArea5_08jan2015_56days.csv"
out_csv = r"C:\Users\mnguyen\Downloads\Prof Bradley\NorCal\08jan2015\NorCal_08jan2015_last28days.csv"

# --- read raw (do NOT parse dates at read time) ---
df = pd.read_csv(in_csv, dtype=str, keep_default_na=False)
df.columns = df.columns.str.strip()

# change if your column name differs
dt_col = 'date'

# --- normalize datetime text ---
s = (df[dt_col].astype(str)
                .str.strip()
                .str.replace(r'\s+', ' ', regex=True))  # collapse double spaces

# strip optional seconds if present (":ss" at the end, before optional AM/PM)
s = s.str.replace(r'(?<=\d):\d{2}(?=\s*(AM|PM)?$)', '', regex=True)

# split by AM/PM presence
has_ampm = s.str.contains(r'\b(AM|PM)\b', case=False, regex=True)
no_ampm  = ~has_ampm

parsed = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')

# with AM/PM (12-hour)
if has_ampm.any():
    parsed.loc[has_ampm] = pd.to_datetime(
        s[has_ampm], format='%m/%d/%Y %I:%M %p', errors='coerce'
    )

# without AM/PM (assume 24-hour)
if no_ampm.any():
    parsed.loc[no_ampm] = pd.to_datetime(
        s[no_ampm], format='%m/%d/%Y %H:%M', errors='coerce'
    )

# final fallback parse for any leftovers
mask_left = parsed.isna()
if mask_left.any():
    parsed.loc[mask_left] = pd.to_datetime(s[mask_left], errors='coerce')

df['_dt'] = parsed
df = df.dropna(subset=['_dt']).copy()

# --- LAST 28 calendar days (inclusive of the latest day) ---
last_day_in_file  = df['_dt'].max().normalize()                   # latest midnight
start_day_incl    = last_day_in_file - pd.Timedelta(days=DAYS-1)  # inclusive window start
end_day_excl      = last_day_in_file + pd.Timedelta(days=1)       # next midnight

last_n = df.loc[(df['_dt'] >= start_day_incl) & (df['_dt'] < end_day_excl)].copy()

# put parsed datetime back (optional)
last_n[dt_col] = last_n['_dt']
last_n.drop(columns=['_dt'], inplace=True)

# --- save ---
last_n.to_csv(out_csv, index=False)

# --- sanity info ---
print("Parsed date range:", df['_dt'].min(), "to", df['_dt'].max())
print("Unique calendar days available:", df['_dt'].dt.normalize().nunique())
print(f"Rows exported (last {DAYS} days):", len(last_n))
print("Saved to:", out_csv)
