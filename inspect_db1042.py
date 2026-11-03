with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_DB1042_Timer.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
matches = re.findall(r'<Member\s+Name="[^"]*DrillDirectionCurrent[^"]*"[^>]*>', txt)
print('DrillDirectionCurrent members:', matches)
