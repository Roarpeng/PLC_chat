with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\005_Component_DB1900_Communication_PC.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
matches = re.findall(r'<Member\s+Name="[^"]*Force[^"]*"[^>]*>', txt)
print('Force members in DB1900:', matches)
