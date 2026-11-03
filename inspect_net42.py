with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
cus = re.findall(r'<SW\.Blocks\.CompileUnit\s+ID="[^"]+"\s+CompositionName="CompileUnits">.*?</SW\.Blocks\.CompileUnit>', txt, re.DOTALL)
print(f"Total CompileUnits: {len(cus)}")
for i in [39, 40, 41, 42]:
    if i < len(cus):
        print(f"=== CompileUnit {i+1} ===")
        print(cus[i])
