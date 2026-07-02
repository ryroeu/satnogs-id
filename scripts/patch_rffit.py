"""Minimal patch: add a non-interactive `-I` flag to rffit that calls its OWN
identify_satellite_from_doppler() against the /null pgplot device and exits -- making rffit's
existing identification usable headless (no X/fonts/keypresses). No estimation is reimplemented."""

import sys

p = sys.argv[1] if len(sys.argv) > 1 else "/opt/strf/rffit.c"
with open(p, encoding="utf-8") as _f:
    s = _f.read()
reps = [
    (
        "int site_number[16],nsite=0,graves=0;",
        "int site_number[16],nsite=0,graves=0,identify_only=0;",
    ),
    ('"d:c:i:hs:gm:F:"', '"d:c:i:hs:gm:F:I"'),
    (
        "    case 'g':\n      graves=1;\n      break;\n",
        "    case 'g':\n      graves=1;\n      break;\n\n"
        "    case 'I':\n      identify_only=1;\n      break;\n",
    ),
    (
        '    fprintf(stderr,"Failed to redirect stderr\\n");\n\n  cpgopen("/xs");',
        '    fprintf(stderr,"Failed to redirect stderr\\n");\n\n'
        "  if (identify_only) {\n"
        "    int _j; for (_j=0;_j<d.n;_j++) d.p[_j].flag=2;\n"
        '    cpgopen("/null");\n'
        "    identify_satellite_from_doppler(tle_array, 1.0e6);\n"
        "    return 0;\n"
        '  }\n\n  cpgopen("/xs");',
    ),
]
for a, b in reps:
    assert a in s, f"patch anchor not found (strf changed?): {a[:60]!r}"
    s = s.replace(a, b, 1)
with open(p, "w", encoding="utf-8") as _f:
    _f.write(s)
print("patched rffit.c: added -I non-interactive identify")
