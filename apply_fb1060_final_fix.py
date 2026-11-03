with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'r', encoding='utf-8') as f:
    txt = f.read()

# 1. Fix Auto_Force -> Auto_Force[5]
txt = txt.replace('"DB1900_Communication_PC".Para.Auto_Force = 0.0', '"DB1900_Communication_PC".Para.Auto_Force[5] = 0.0')
txt = txt.replace('"DB1900_Communication_PC".Para.Auto_Force = 0.0))', '"DB1900_Communication_PC".Para.Auto_Force[5] = 0.0))')

# 2. Restore .TON calls on timers
txt = txt.replace('"Timer_RecvEmmMode"(IN :=', '"Timer_RecvEmmMode".TON(IN :=')
txt = txt.replace('"Timer_ParaWriteOuttime"(IN :=', '"Timer_ParaWriteOuttime".TON(IN :=')

with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'w', encoding='utf-8', newline='\r\n') as f:
    f.write(txt)

print("Applied fix to FB1060_AutoStep.scl successfully.")
