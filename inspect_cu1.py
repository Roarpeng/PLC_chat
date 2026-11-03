with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml', 'r', encoding='utf-8') as f:
    txt = f.read()

import re
cu1 = re.search(r'<SW\.Blocks\.CompileUnit\s+ID="5"[^>]*>.*?</SW\.Blocks\.CompileUnit>', txt, re.DOTALL)
if cu1:
    content = cu1.group(0)
    # print all Parts in cu1
    parts = re.findall(r'<Part\s+Name="([^"]+)"[^>]*>', content)
    calls = re.findall(r'<CallInfo\s+Name="([^"]+)"[^>]*>', content)
    symbols = re.findall(r'<Component\s+Name="([^"]+)"\s*/>', content)
    print("Parts:", parts)
    print("Calls:", calls)
    print("Symbols:", symbols)
