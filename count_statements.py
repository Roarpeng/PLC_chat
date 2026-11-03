with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'r', encoding='utf-8') as f:
    txt = f.read()

body = txt[txt.find('BEGIN'):]
# split into lines
stmts = []
for line in body.splitlines():
    cleaned = line.split('//')[0].strip()
    if cleaned and cleaned not in ['BEGIN', 'END_FUNCTION_BLOCK']:
        stmts.append(cleaned)

print(f"Total executable statements: {len(stmts)}")
for i, s in enumerate(stmts, 1):
    if i in [1, 2, 3, 4, 17, 41, 150, 151] or (i >= 38 and i <= 44):
        print(f"Statement {i:3d}: {s}")
