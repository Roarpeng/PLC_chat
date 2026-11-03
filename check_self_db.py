import glob
import os
import re

for fp in glob.glob('PLC_Openness_data/hr001/pure_scl_fbs/*.scl'):
    base = os.path.splitext(os.path.basename(fp))[0]
    num = ''.join([c for c in base if c.isdigit()])
    if num:
        db_name = f'DB{num}'
        txt = open(fp, 'r', encoding='utf-8-sig').read()
        # Find any occurrence of "DB<num>_..."
        matches = re.findall(rf'"{db_name}_[a-zA-Z0-9_]+"', txt)
        if matches:
            print(f'{base}: references self DB: {set(matches)}')
