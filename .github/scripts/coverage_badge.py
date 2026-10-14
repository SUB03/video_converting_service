"""Turn coverage.py's coverage.json into a shields.io endpoint badge JSON.

Usage: python coverage_badge.py coverage.json badge.json
"""
import json
import sys

src, dest = sys.argv[1], sys.argv[2]
percent = round(json.load(open(src))["totals"]["percent_covered"])

if percent >= 90:
    color = "brightgreen"
elif percent >= 75:
    color = "green"
elif percent >= 60:
    color = "yellow"
else:
    color = "red"

with open(dest, "w") as f:
    json.dump({"schemaVersion": 1, "label": "coverage", "message": f"{percent}%", "color": color}, f)
print(f"coverage {percent}% ({color})")
