with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB720_KuKa_MainCtrl.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
matches = re.findall(r'<Member\s+Name="[^"]*ToolTypeNo[^"]*"[^>]*>', txt)
print('ToolTypeNo members:', matches)
