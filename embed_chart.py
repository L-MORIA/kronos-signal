"""Embed chart PNG as base64 into HTML."""
import base64
import os

png_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sberp-5min-chart.png")
html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sberp-chart-embedded.html")

with open(png_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>SBERP 5-min Chart</title>
<style>
  body {{ background: #0f0f1a; color: #ccc; font-family: monospace; display: flex; flex-direction: column; align-items: center; padding: 20px; margin: 0; }}
  h1 {{ color: #00d2ff; font-size: 22px; }}
  .sub {{ color: #667; font-size: 13px; }}
  img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 0 30px rgba(0,210,255,0.15); }}
</style>
</head>
<body>
<h1>SBERP &mdash; 5-min Chart (2026-07-06)</h1>
<div class="sub">MOEX ISS | Last 5-min: 15:15 MSK O=302.21 H=302.31 L=301.69 C=301.93</div>
<img src="data:image/png;base64,{b64}" alt="SBERP Chart">
</body>
</html>"""

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"HTML saved: {html_path}")
print(f"Base64 size: {len(b64)} chars")
