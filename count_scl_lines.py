with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'r', encoding='utf-8') as f:
    lines = f.readlines()

no_comments = []
for i, l in enumerate(lines, 1):
    cleaned = l.split('//')[0].strip()
    if cleaned:
        no_comments.append((i, cleaned))

print("Total non-comment lines:", len(no_comments))
for idx, (orig_line, text) in enumerate(no_comments, 1):
    if idx in [17, 41, 151] or (idx >= 38 and idx <= 45):
        print(f"Non-comment line {idx:3d} (Orig line {orig_line:3d}): {text}")
