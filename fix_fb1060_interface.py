with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'r', encoding='utf-8') as f:
    txt = f.read()

body_start = txt.find('BEGIN')
body = txt[body_start:]

# Fix timer calls in body
body = body.replace('"Timer_RecvEmmMode".TON(', '"Timer_RecvEmmMode"(')
body = body.replace('"Timer_ParaWriteOuttime".TON(', '"Timer_ParaWriteOuttime"(')

new_header = """FUNCTION_BLOCK "FB1060_AutoStep"
{ S7_Optimized_Access := 'FALSE' }
// 编号：FB1060
// 原始语言：LAD（规则翻译为 SCL）
// 含义：自动循环起点
VAR
    Status : Struct  // 状态
        Running : Bool;  // 自动运行中
        OkToStart : Bool;  // 设备可以启动
        FirstStart : Bool;  // 换枪后第一次
    END_STRUCT;
    Aux : Struct  // 静态变量
        HoleNo : Int;  // 工作流程数
    END_STRUCT;
    EdgeDetc : Struct  // 静态变量
        Pulse : Array[0..15] of Bool;  // 静态变量
    END_STRUCT;
    MainStep : "UDT_Step";  // 自动流程步
    CycleTime : "FB5008_CycleTime";  // 静态变量
    RobotAutoStep : "FB1061_RobotAutoStep";  // 静态变量
    HorDrillAutoStep : "FB1062_HorDrillAutoStep";  // 静态变量
    DownDrillAutoStep : "FB1063_DownDrillAutoStep";  // 静态变量
    DiamondAutoStep : "FB1064_DiamondAutostep";  // 静态变量
END_VAR
VAR_TEMP
    StepPls : Bool;
END_VAR
"""

new_content = new_header + body
with open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'w', encoding='utf-8', newline='\r\n') as f:
    f.write(new_content)

print(f"Updated FB1060_AutoStep.scl successfully ({len(new_content)} bytes).")
