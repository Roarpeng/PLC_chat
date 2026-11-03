import glob
import os
import re

# Collect all array members from all DB XML files in export
array_members = {}
for fp in glob.glob(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\*.xml'):
    txt = open(fp, 'r', encoding='utf-8', errors='ignore').read()
    # Find <Member Name="..." Datatype="Array[...]"
    for m in re.finditer(r'<Member\s+Name="([^"]+)"\s+Datatype="Array\[', txt):
        array_members[m.group(1)] = fp

print(f"Found {len(array_members)} array members in DBs: {list(array_members.keys())}")

# Check across all 40 FBs
for fp in glob.glob(r'PLC_Openness_data\hr001\pure_scl_fbs\*.scl'):
    txt = open(fp, 'r', encoding='utf-8').read()
    fname = os.path.basename(fp)
    for arr in array_members:
        # Search for .arr or #arr not followed by [ or a word char
        bad = re.findall(r'[\.#]' + re.escape(arr) + r'(?!\[|[a-zA-Z0-9_])', txt)
        if bad:
            # check if it's a full array assignment (like #arr := other_arr)
            print(f"{fname}: Unindexed DB array '{arr}' (count={len(bad)})")
