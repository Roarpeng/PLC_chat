with open(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    if 'Timer_RecvEmmMode' in l:
        for j in range(max(0, i-20), min(len(lines), i+20)):
            print(f"{j+1}: {lines[j].rstrip()}")
        break
