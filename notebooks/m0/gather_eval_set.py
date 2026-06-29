"""Host-side: build a larger eval set for the Geoscan cluster -- for each of the 6
near-identical Geoscan objects, download up to K strong (with-signal, .h5) passes from
distinct stations, and write each pass's epoch-matched candidate catalog. -> /scratch/eval/."""
import json, os, urllib.request, urllib.error
from datetime import datetime
SC = "/private/tmp/claude-501/-Users-ryan-GitHub-satnogs-id/e9fc3766-e6dd-4352-9d46-489818e4c3a6/scratchpad"
KEY = None
for line in open('/Users/ryan/GitHub/satnogs-id/.env'):
    if line.startswith('satnogs_db_api_key='): KEY = line.strip().split('=',1)[1]
def getj(url, auth=False):
    h = {'Accept':'application/json'}
    if auth: h['Authorization'] = f'Token {KEY}'
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30))
GEOSCANS = {64879:'Geoscan-6', 64880:'Geoscan-1', 64890:'Geoscan-2',
            64891:'Geoscan-5', 64892:'Geoscan-4', 64893:'Geoscan-3'}
soup = list(range(64876, 64896))
K = 12
os.makedirs(SC+'/eval', exist_ok=True)
cand_obs = {n: getj(f'https://network.satnogs.org/api/observations/?norad_cat_id={n}&format=json') for n in soup}
downloaded = []
import glob as _glob
existing = {os.path.basename(p).split('_')[0][3:] for p in _glob.glob(SC+'/eval/*.h5')}
for norad, name in GEOSCANS.items():
    cands = sorted([o for o in cand_obs[norad]
                    if o.get('waterfall_status') == 'with-signal' and (o.get('max_altitude') or 0) >= 25],
                   key=lambda o: -(o.get('max_altitude') or 0))
    got = 0
    for o in cands:
        if got >= K: break
        oid = o['id']; st = o.get('ground_station')
        fn = f'{SC}/eval/obs{oid}_n{norad}_st{st}.h5'
        if str(oid) in existing or os.path.exists(fn):
            downloaded.append((oid, norad)); got += 1; continue
        rows = getj(f'https://db.satnogs.org/api/artifacts/?network_obs_id={oid}&format=json', auth=True)
        rows = rows if isinstance(rows, list) else rows.get('results', [])
        url = next((a['artifact_file'] for a in rows if a.get('artifact_file')), None)
        if not url: continue
        try: urllib.request.urlretrieve(url, fn)
        except urllib.error.HTTPError:
            req = urllib.request.Request(url, headers={'Authorization': f'Token {KEY}'})
            open(fn, 'wb').write(urllib.request.urlopen(req, timeout=90).read())
        downloaded.append((oid, norad)); got += 1
    print(f'{name} ({norad}): {got} passes')
# per-obs epoch-matched catalogs
for oid, norad in downloaded:
    tdate = datetime.fromisoformat(getj(f'https://network.satnogs.org/api/observations/?id={oid}&format=json')[0]['start'][:10])
    lines = []
    for n in soup:
        best, bd = None, 1e9
        for o in cand_obs[n]:
            if not o.get('tle1'): continue
            dd = abs((datetime.fromisoformat(o['start'][:10]) - tdate).days)
            if dd < bd: bd = dd; best = o
        if best: lines += [(best.get('tle0') or '0 OBJECT').strip(), best['tle1'], best['tle2']]
    open(f'{SC}/eval/soup_{oid}.tle', 'w').write('\n'.join(lines)+'\n')
print(f'\neval set: {len(downloaded)} passes across {len(GEOSCANS)} near-identical objects')
