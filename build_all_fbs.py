import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
fbs_dir = ROOT / 'PLC_Openness_data' / 'hr001' / 'pure_scl_fbs'
files = sorted(fbs_dir.glob('*.scl'))

dep_graph = {}
block_contents = {}

for fp in files:
    name = Path(fp).stem
    txt = open(fp, 'r', encoding='utf-8-sig').read().strip()
    block_contents[name] = txt

    callees = set()
    for other in [Path(f).stem for f in files]:
        if other != name and (f'"{other}"' in txt or f'{other}.' in txt or f'"{other}"(' in txt):
            callees.add(other)
    dep_graph[name] = callees

ordered = []
visited = set()
visiting = set()

def visit(n):
    if n in visiting:
        return
    if n not in visited:
        visiting.add(n)
        for dep in dep_graph.get(n, []):
            if dep != 'FB1003_CR':
                visit(dep)
        visiting.remove(n)
        visited.add(n)
        ordered.append(n)

for b in sorted(block_contents.keys()):
    if b != 'FB1003_CR':
        visit(b)

print(f"Topologically ordered {len(ordered)} blocks (excluding FB1003_CR which is already SCL and protected):")
for i, b in enumerate(ordered, 1):
    print(f"{i:2d}. {b} (callees: {list(dep_graph[b])})")

out_path = ROOT / 'PLC_Openness_data' / 'hr001' / 'All_40_Refactored_FBs.scl'
with open(out_path, 'w', encoding='utf-8-sig', newline='\r\n') as out_f:
    for b in ordered:
        out_f.write(f'// ============================================================\r\n')
        out_f.write(f'// Block: {b}\r\n')
        out_f.write(f'// ============================================================\r\n')
        out_f.write(block_contents[b] + '\r\n\r\n')

print(f"Successfully wrote {len(ordered)} blocks to {out_path} ({out_path.stat().st_size} bytes).")
