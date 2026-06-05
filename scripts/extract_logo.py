"""Extracts RUCKUS_LOGO_PNG_B64 from RUCKUS/ruckus_dashboard.py into
RUCKUS/ruckus_dashboard/static/assets/ruckus-logo.png."""
import base64
import pathlib
import re

src = pathlib.Path("RUCKUS/ruckus_dashboard.py").read_text(encoding="utf-8")
m = re.search(r'RUCKUS_LOGO_PNG_B64\s*=\s*"([^"]+)"', src)
if not m:
    raise SystemExit("RUCKUS_LOGO_PNG_B64 not found in source")
out = pathlib.Path("RUCKUS/ruckus_dashboard/static/assets/ruckus-logo.png")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(base64.b64decode(m.group(1)))
print(f"wrote {out} ({out.stat().st_size} bytes)")
