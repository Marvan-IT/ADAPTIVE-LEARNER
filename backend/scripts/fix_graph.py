"""One-shot script: add cross-chapter sequential edges to graph.json.

After running, restart the backend so _graph_cache is cleared.
"""
import json
from pathlib import Path

path = Path("output/prealgebra/graph.json")
data = json.loads(path.read_text(encoding="utf-8"))
nodes, edges = data["nodes"], data["edges"]

# Find max section per chapter (= last node of that chapter)
chapters = {}
for n in nodes:
    num = n["id"].split("_")[-1]   # e.g. "1.5", "2.4"
    parts = num.split(".")
    if len(parts) != 2:
        continue
    ch = int(parts[0])
    sec = float(num)
    if ch not in chapters or sec > chapters[ch][0]:
        chapters[ch] = (sec, n["id"])

existing = {(e["source"], e["target"]) for e in edges}
added = []
for ch in sorted(chapters):
    next_ch = ch + 1
    if next_ch not in chapters:
        continue
    src = chapters[ch][1]             # last section of ch N
    tgt = f"prealgebra_{next_ch}.1"   # first section of ch N+1
    if (src, tgt) not in existing:
        edges.append({"source": src, "target": tgt})
        added.append(f"  {src} → {tgt}")

data["edges"] = edges
path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Added {len(added)} cross-chapter edges:")
for e in added:
    print(e)
print("Done. Restart the backend to reload the graph cache.")
