import re
from pathlib import Path

fbs_dir = Path(__file__).resolve().parent / 'PLC_Openness_data' / 'hr001' / 'pure_scl_fbs'

def update_file(filename, fn):
    path = fbs_dir / filename
    txt = open(path, 'r', encoding='utf-8-sig').read()
    new_txt = fn(txt)
    with open(path, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(new_txt)
    print(f"Updated {filename}")

# 1. FB1080_Component.scl
def fix_fb1080(txt):
    txt = txt.replace('"DB1080_Component".', '#')
    return txt
update_file('FB1080_Component.scl', fix_fb1080)

# 2. FB1081_ValveCall.scl
def fix_fb1081(txt):
    txt = txt.replace('"DB1081_ValveCall".', '#')
    return txt
update_file('FB1081_ValveCall.scl', fix_fb1081)

# 3. FB720_KuKa_MainCtrl.scl
def fix_fb720(txt):
    txt = txt.replace('"DB720_KuKa_MainCtrl".', '#')
    return txt
update_file('FB720_KuKa_MainCtrl.scl', fix_fb720)

# 4. FB1910_DrillData.scl
def fix_fb1910(txt):
    txt = txt.replace('"DB1910_DrillData".', '#')
    return txt
update_file('FB1910_DrillData.scl', fix_fb1910)

# 5. FB5008_CycleTime.scl
def fix_fb5008(txt):
    txt = re.sub(
        r'"SyS_Time"\s*:=\s*"DB1001_SysMode"\.Sys_Time\.CurPLCTime;.*?$',
        r'"SyS_Time" := DTL_TO_TOD("DB1001_SysMode".Sys_Time.CurPLCTime);',
        txt, flags=re.MULTILINE
    )
    return txt
update_file('FB5008_CycleTime.scl', fix_fb5008)

# 6. FB1001_SysMode.scl
def fix_fb1001(txt):
    txt = re.sub(
        r'RD_SYS_T\(RET_VAL\s*:=\s*#RetVal,\s*OUT\s*:=\s*#Sys_Time\.CurPLCTime\);',
        r'#RetVal := RD_SYS_T(#Sys_Time.CurPLCTime);',
        txt
    )
    txt = re.sub(
        r'WR_SYS_T\(EN\s*:=\s*#Cmd\.SetTime,\s*IN\s*:=\s*#Sys_Time\.SetPLCTimeTP,\s*RET_VAL\s*:=\s*#RetVal\);',
        r'IF #Cmd.SetTime THEN #RetVal := WR_SYS_T(#Sys_Time.SetPLCTimeTP); END_IF;',
        txt
    )
    txt = re.sub(
        r'"SyS_Time"\s*:=\s*#Sys_Time\.CurPLCTime;.*?$',
        r'"SyS_Time" := DTL_TO_TOD(#Sys_Time.CurPLCTime);',
        txt, flags=re.MULTILINE
    )
    return txt
update_file('FB1001_SysMode.scl', fix_fb1001)

# 7. FB5003_FixtureID.scl
def fix_fb5003(txt):
    old_net1 = """    IF #i_ID00 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 #i_ID01 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF #i_ID01 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 #i_ID02 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF #i_ID02 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 #i_ID03 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF #i_ID03 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 #i_ID04 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF #i_ID04 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 #i_ID05 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF #i_ID05 THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 NOT (TRUE) 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF NOT (TRUE) THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;
    // 含义：当 NOT (TRUE) 为 TRUE 时置位 #TP_CurFixtureID，否则复位（触点→线圈）
    IF NOT (TRUE) THEN #TP_CurFixtureID := TRUE; ELSE #TP_CurFixtureID := FALSE; END_IF;"""

    new_net1 = """    #TP_CurFixtureID.%X0 := #i_ID00;
    #TP_CurFixtureID.%X1 := #i_ID01;
    #TP_CurFixtureID.%X2 := #i_ID02;
    #TP_CurFixtureID.%X3 := #i_ID03;
    #TP_CurFixtureID.%X4 := #i_ID04;
    #TP_CurFixtureID.%X5 := #i_ID05;
    #TP_CurFixtureID.%X6 := FALSE;
    #TP_CurFixtureID.%X7 := FALSE;"""
    if old_net1 in txt:
        txt = txt.replace(old_net1, new_net1)
    else:
        # Regex replacement if whitespace differs
        txt = re.sub(r'IF\s+#i_ID00\s+THEN\s+#TP_CurFixtureID.*?IF\s+NOT\s*\(TRUE\)\s+THEN\s+#TP_CurFixtureID\s*:=\s*TRUE;\s*ELSE\s*#TP_CurFixtureID\s*:=\s*FALSE;\s*END_IF;', new_net1, txt, flags=re.DOTALL)
    return txt
update_file('FB5003_FixtureID.scl', fix_fb5003)

# 8. FB2009_CoolingFanFunction.scl
def fix_fb2009(txt):
    old_call = """    #Timer_StationToolOn.TON(IN := (#Auto_Mode AND #I_StationToolOn_1) AND #I_StationToolOn_2, PT := T#2s);
    // 含义：调用块/实例 #SR_StationTool.SR，参数：R1 := NOT (#I_StationToolOn_1) OR NOT (#I_StationToolOn_2) OR #Timer_StationCoolingFan.Q OR #Man_Mode OR #Emm_Mode, S := #Timer_StationToolOn.Q
    #SR_StationTool.SR(R1 := NOT (#I_StationToolOn_1) OR NOT (#I_StationToolOn_2) OR #Timer_StationCoolingFan.Q OR #Man_Mode OR #Emm_Mode, S := #Timer_StationToolOn.Q);
    // 含义：当 #SR_StationTool.Q 为 TRUE 时置位 #ToolAtPos，否则复位（触点→线圈）
    IF #SR_StationTool.Q THEN #ToolAtPos := TRUE; ELSE #ToolAtPos := FALSE; END_IF;
    // 含义：调用定时器实例 #Timer_StationCoolingFan.TON
    #Timer_StationCoolingFan.TON(IN := #SR_StationTool.Q, PT := #CoolingTime);"""

    new_call = """    #Timer_StationToolOn(IN := (#Auto_Mode AND #I_StationToolOn_1) AND #I_StationToolOn_2, PT := T#2s);
    IF (NOT (#I_StationToolOn_1) OR NOT (#I_StationToolOn_2) OR #Timer_StationCoolingFan.Q OR #Man_Mode OR #Emm_Mode) THEN
        #SR_StationTool := FALSE;
    ELSIF #Timer_StationToolOn.Q THEN
        #SR_StationTool := TRUE;
    END_IF;
    #ToolAtPos := #SR_StationTool;
    #Timer_StationCoolingFan(IN := #SR_StationTool, PT := #CoolingTime);"""
    
    if old_call in txt:
        txt = txt.replace(old_call, new_call)
    else:
        txt = re.sub(r'#Timer_StationToolOn\.TON.*?#Timer_StationCoolingFan\.TON\(IN\s*:=\s*#SR_StationTool\.Q,\s*PT\s*:=\s*#CoolingTime\);', new_call, txt, flags=re.DOTALL)
    return txt
update_file('FB2009_CoolingFanFunction.scl', fix_fb2009)

# 9. FB2008_CoolingFan.scl
def fix_fb2008(txt):
    txt = txt.replace('#A Station CoolingFan(', '#"A Station CoolingFan"(')
    txt = txt.replace('#B Station CoolingFan(', '#"B Station CoolingFan"(')
    txt = txt.replace(
        '#C Station CoolingFan(Man_Mode := "ManMode_M", Auto_Mode := "AutoMode_M", Emm_Mode := "EMMode_M", CoolingTime := T#30M, Q_StationCoolingFan => "QCStationFan");',
        '#"C Station CoolingFan"(Man_Mode := "ManMode_M", Auto_Mode := "AutoMode_M", Emm_Mode := "EMMode_M", I_StationToolOn_1 := FALSE, I_StationToolOn_2 := FALSE, CoolingTime := T#30M, Q_StationCoolingFan => "QCStationFan");'
    )
    return txt
update_file('FB2008_CoolingFan.scl', fix_fb2008)

# 10. FB5699_RandomDemoTest.scl
def fix_fb5699(txt):
    txt = re.sub(
        r'\("SyS_Time"\s+MOD\s+2\)',
        r'(TOD_TO_DINT("SyS_Time") MOD 2)',
        txt
    )
    txt = txt.replace('JMP Jump;', 'GOTO Jump;')
    # Add Jump label before #Step.Main.RandomTestCycleReStart := FALSE;
    if 'Jump: ;' not in txt:
        txt = txt.replace(
            '#Step.Main.RandomTestCycleReStart := FALSE;',
            'Jump: ;\r\n    #Step.Main.RandomTestCycleReStart := FALSE;'
        )
    return txt
update_file('FB5699_RandomDemoTest.scl', fix_fb5699)

# 11. FB5715_Kuka_General.scl
def fix_fb5715(txt):
    txt = txt.replace('#Step.Main := #Stack.Step.Stack.Index;', '#Step.Main := #Stack.Step[#Stack.Index];')
    if '_Scan_Case: ;' not in txt:
        txt = txt.replace('CASE #Step.Main OF', '_Scan_Case: ;\r\n        CASE #Step.Main OF')
    txt = re.sub(r'GOTO\s*;', 'GOTO _Scan_Case;', txt)
    return txt
update_file('FB5715_Kuka_General.scl', fix_fb5715)

# 12. FB1010_Parameter.scl
def fix_fb1010(txt):
    txt = txt.replace('"DB5000_ParameterLoadMemory".AryTypePara.Aux.WriteTypeParaDBL.Index', '"DB5000_ParameterLoadMemory".AryTypePara[#Aux.WriteTypeParaDBL.Index]')
    txt = txt.replace('"DB5000_ParameterLoadMemory".AryTypePara.Aux.ReadTypeParaDBL.Index', '"DB5000_ParameterLoadMemory".AryTypePara[#Aux.ReadTypeParaDBL.Index]')
    txt = txt.replace('#At_TypeName.Aux.ReadTypeNameIndex', '#At_TypeName[#Aux.ReadTypeNameIndex]')
    txt = txt.replace('#AryTypeName.Aux.ReadTypeNameIndex', '#AryTypeName[#Aux.ReadTypeNameIndex]')
    txt = txt.replace('#ArrayProgNoForSel.Aux.ReadTypeNameIndex', '#ArrayProgNoForSel[#Aux.ReadTypeNameIndex]')
    
    # In step 410, 510, 610:
    txt = txt.replace('#At_TypeName := 20;\r\n            #AryTypeName := #Aux.AuxTypePara.TypeName;', '#AryTypeName[11] := #Aux.AuxTypePara.TypeName;')
    txt = txt.replace('#At_TypeName := 20;\r\n            #Aux.AuxTypePara.TypeName := #AryTypeName;', '#Aux.AuxTypePara.TypeName := #AryTypeName[11];')
    txt = txt.replace('#At_TypeName := 20;\n            #AryTypeName := #Aux.AuxTypePara.TypeName;', '#AryTypeName[11] := #Aux.AuxTypePara.TypeName;')
    txt = txt.replace('#At_TypeName := 20;\n            #Aux.AuxTypePara.TypeName := #AryTypeName;', '#Aux.AuxTypePara.TypeName := #AryTypeName[11];')
    return txt
update_file('FB1010_Parameter.scl', fix_fb1010)

print("All specific FB fixes applied successfully.")
