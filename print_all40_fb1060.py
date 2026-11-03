with open(r'PLC_Openness_data\hr001\All_40_Refactored_FBs.scl', 'r', encoding='utf-8') as f:
    lines = f.readlines()

fb_start = 0
for i, l in enumerate(lines):
    if 'FUNCTION_BLOCK "FB1060_AutoStep"' in l:
        fb_start = i
        break

print(f'FB1060 starts at All_40 line {fb_start + 1}')
for j in range(fb_start, min(fb_start + 50, len(lines))):
    rel = j - fb_start + 1
    print(f'Block line {rel:3d} (File line {j+1:4d}): {lines[j].rstrip()}')
