import pandas as pd
import re

# --- params ---
DAYS = 28  # number of calendar days to keep from the earliest timestamp

# --- paths ---
in_csv  = r"C:\Users\mnguyen\Downloads\Prof Bradley\Seattle\IFR_MetroArea7_01apr2015_56days.csv"
out_csv = r"C:\Users\mnguyen\Downloads\Prof Bradley\Seattle\Seattle_first28days.csv"

# --- read raw (do NOT parse dates at read time) ---
df = pd.read_csv(in_csv, dtype=str, keep_default_na=False)
df.columns = df.columns.str.strip()

# set your actual column name here if it's not exactly 'date'
dt_col = 'date'

# --- normalize the datetime text ---
# 1) ensure string, trim, collapse multiple spaces
s = (df[dt_col].astype(str)
                .str.strip()
                .str.replace(r'\s+', ' ', regex=True))  # "5/4/2013  1:23" -> "5/4/2013 1:23"

# 2) remove optional seconds if present (":ss")
#    e.g., "5/4/2013 1:23:00 AM" -> "5/4/2013 1:23 AM"; "5/4/2013 13:23:05" -> "5/4/2013 13:23"
s = s.str.replace(r'(?<=\d):\d{2}(?=\s*(AM|PM)?$)', '', regex=True)

# --- split rows by whether they have AM/PM or not ---
has_ampm = s.str.contains(r'\b(AM|PM)\b', case=False, regex=True)
no_ampm  = ~has_ampm

# --- parse both groups with explicit formats ---
parsed = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')

# With AM/PM (12-hour)
if has_ampm.any():
    parsed.loc[has_ampm] = pd.to_datetime(
        s[has_ampm],
        format='%m/%d/%Y %I:%M %p',
        errors='coerce'
    )

# Without AM/PM (assume 24-hour)
if no_ampm.any():
    parsed.loc[no_ampm] = pd.to_datetime(
        s[no_ampm],
        format='%m/%d/%Y %H:%M',
        errors='coerce'
    )

# If any leftovers failed, last-resort try pandas' general parser
mask_left = parsed.isna()
if mask_left.any():
    parsed.loc[mask_left] = pd.to_datetime(s[mask_left], errors='coerce')

# keep only successfully parsed rows
df['_dt'] = parsed
df = df.dropna(subset=['_dt']).copy()

# --- compute FIRST 28 calendar days from the earliest timestamp ---
start_day = df['_dt'].min().normalize()
end_day   = start_day + pd.Timedelta(days=DAYS)  # exclusive
first_n   = df.loc[df['_dt'] < end_day].copy()

# put the parsed datetime back into the original column (optional)
first_n[dt_col] = first_n['_dt']
first_n.drop(columns=['_dt'], inplace=True)

# --- save ---
first_n.to_csv(out_csv, index=False)

print("Parsed date range:", df['_dt'].min(), "to", df['_dt'].max())
print("Unique calendar days available:", df['_dt'].dt.normalize().nunique())
print(f"Exported rows (first {DAYS} days):", len(first_n))
print("Saved to:", out_csv)
