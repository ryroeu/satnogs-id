"""Build strf inputs from a SatNOGS .h5 (Geoscan-2, obs 12945145), following the
authoritative satnogs_waterfall_tabulation_helper.py recipe:
  1. extract the near-vertical signal track from the (Doppler-CORRECTED) waterfall,
  2. UN-correct it with the obs TLE: freq_recv = f_center + offset - f_center*range_rate/c,
  3. write rffit's .dat (MJD, freq_recv, weight, site), the candidate catalog, and the site.
Then rffit's identify ('i') matches the recovered Doppler curve against the catalog."""
import h5py, json, numpy as np, os
from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84, EarthSatellite
C = 299792.458; SITE = 9001
f = h5py.File('/data/good.h5','r'); m = json.loads(f.attrs['metadata'])
f0 = float(m['frequency']); loc = m['location']; t0 = m['tle'].strip().splitlines()
wf = f['waterfall']; data = wf['data'][:]; freqax = wf['frequency'][:].astype(float)
scale = wf['scale'][:].astype(float); offset = wf['offset'][:].astype(float); relt = wf['relative_time'][:].astype(float)
_st = wf.attrs['start_time']; _st = _st.decode() if isinstance(_st, bytes) else _st
start = datetime.fromisoformat(_st.replace('Z','+00:00'))
T, F = data.shape
dB = data.astype(np.float32)*scale[None,:] + offset[None,:]

# 1. extract near-vertical signal track: per-row peak, keep high-SNR rows near the carrier column
peak = np.argmax(dB, axis=1); peakp = dB[np.arange(T), peak]; base = np.median(dB, axis=1); snr = peakp - base
hi = snr >= np.percentile(snr, 85)
carrier = float(np.median(freqax[peak[hi]]))
keep = hi & (np.abs(freqax[peak] - carrier) < 6000)
idx = np.where(keep)[0]
print(f'extracted {len(idx)}/{T} track points; carrier offset ~{carrier:.0f} Hz')

# 2. un-correct with the obs TLE (skyfield), exactly per the helper
ts = load.timescale(builtin=True); st = wgs84.latlon(loc['latitude'], loc['longitude'], elevation_m=loc['altitude'])
sat = EarthSatellite(t0[1], t0[2], 'x', ts)
EPOCH = datetime(1858,11,17, tzinfo=timezone.utc)
rows = []
for i in idx:
    dt = start + timedelta(seconds=float(relt[i]))
    pos = (sat - st).at(ts.from_datetime(dt)); r = pos.position.km; v = pos.velocity.km_per_s
    rr = float(np.sum(r*v)/np.linalg.norm(r))             # km/s, + = receding
    freq_recv = f0 + float(freqax[peak[i]]) - f0*rr/C      # un-correct
    rows.append(((dt-EPOCH).total_seconds()/86400.0, freq_recv))
rows.sort()
os.makedirs('/data/strf', exist_ok=True)
with open('/data/strf/geoscan.dat','w') as g:
    for mj, fr in rows: g.write(f'{mj:.6f}\t{fr:.2f}\t1.0\t{SITE}\n')
fr_lo, fr_hi = min(r[1] for r in rows), max(r[1] for r in rows)
print(f'wrote geoscan.dat: {len(rows)} pts, recv-freq span {(fr_hi-fr_lo)/1e3:.1f} kHz around {f0/1e6:.4f} MHz '
      f'(expect ~Doppler swing if extraction good)')

# 3. candidate catalog (3LE) + site
soup = json.load(open('/data/soup_tles.json'))
with open('/data/strf/soup.tle','w') as g:
    for n, d in soup.items(): g.write(f"{d.get('tle0') or '0 OBJECT'}\n{d['tle1']}\n{d['tle2']}\n")
print(f'wrote soup.tle: {len(soup)} candidates (true = 64890 / Geoscan-2)')
with open('/opt/strf/data/sites.txt','a') as g:
    g.write(f"{SITE} GS {loc['latitude']:.4f} {loc['longitude']:.4f} {int(loc['altitude'])} GeoscanStation\n")
print(f'appended site {SITE} ({loc["latitude"]},{loc["longitude"]}) to sites.txt')
