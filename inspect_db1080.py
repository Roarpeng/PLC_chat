with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\005_Component_DB1080_Component.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
matches = re.findall(r'<Member\s+Name="[^"]*ProgNo[^"]*"[^>]*>', txt)
print('ProgNo members:', matches)
matches2 = re.findall(r'<Member\s+Name="[^"]*RobotSpeed[^"]*"[^>]*>', txt)
print('RobotSpeed members:', matches2)
