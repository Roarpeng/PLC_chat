"""State machine for the AF double-acting cylinder control module."""
from __future__ import annotations

ALARM_EXTEND_TIMEOUT = 1001
ALARM_RETRACT_TIMEOUT = 1002
ALARM_COMMAND_CONFLICT = 1003
ALARM_FEEDBACK_CONFLICT = 1004
ALARM_INVALID_REQUEST = 1005


def emit_cylinder(fb):
    block = fb(
        "FB_AF_DRV_cylinder",
        ["Permit : Bool", "Enable : Bool", "Mode : USInt", "ManualRequest : USInt", "Reset : Bool",
         "ExtendTimeout : Time", "RetractTimeout : Time", "Req_extend : Bool", "Req_retract : Bool",
         "In_extended : Bool", "In_retracted : Bool"],
        ["Fault : Bool", "Q_extend : Bool", "Q_retract : Bool", "State_extended : Bool", "State_retracted : Bool",
         "Ready : Bool", "Busy : Bool", "Done : Bool", "State : DInt", "AlarmId : DInt", "Blocked : Bool", "ActiveRequest : USInt"],
        ["TExtend : TON_TIME", "TRetract : TON_TIME", "ManualArmed : Bool", "Request : USInt", "AllowsMotion : Bool"],
    )
    for line in [
        "#State_extended := #In_extended;",
        "#State_retracted := #In_retracted;",
        "#AllowsMotion := #Enable AND #Permit AND NOT #Reset;",
        "IF (#Mode <> 1) OR NOT #AllowsMotion THEN",
        "    #ManualArmed := FALSE;",
        "ELSIF #ManualRequest = 0 THEN",
        "    #ManualArmed := TRUE;",
        "END_IF;",
        "#Request := 0;",
        "IF #AllowsMotion AND (#AlarmId = 0) THEN",
        "    IF #In_extended AND #In_retracted THEN",
        f"        #AlarmId := {ALARM_FEEDBACK_CONFLICT};",
        "    ELSIF #Mode = 0 THEN",
        "        IF (#Req_extend AND #Req_retract) THEN",
        f"            #AlarmId := {ALARM_COMMAND_CONFLICT};",
        "        ELSIF #Req_extend THEN",
        "            #Request := 1;",
        "        ELSIF #Req_retract THEN",
        "            #Request := 2;",
        "        END_IF;",
        "    ELSIF #Mode = 1 THEN",
        "        IF #ManualArmed AND (#ManualRequest <= 2) THEN",
        "            #Request := #ManualRequest;",
        "        ELSIF #ManualRequest > 2 THEN",
        f"            #AlarmId := {ALARM_INVALID_REQUEST};",
        "        END_IF;",
        "    ELSE",
        f"        #AlarmId := {ALARM_INVALID_REQUEST};",
        "    END_IF;",
        "END_IF;",
        "#TExtend(IN := (#Request = 1) AND NOT #In_extended AND ((#Mode = 1) OR (#ExtendTimeout > T#0ms)),",
        "    PT := SEL(G := #ExtendTimeout > T#0ms, IN0 := T#2000ms, IN1 := #ExtendTimeout));",
        "#TRetract(IN := (#Request = 2) AND NOT #In_retracted AND ((#Mode = 1) OR (#RetractTimeout > T#0ms)),",
        "    PT := SEL(G := #RetractTimeout > T#0ms, IN0 := T#2000ms, IN1 := #RetractTimeout));",
        "IF #Reset THEN",
        "    #AlarmId := 0;",
        "ELSIF #TExtend.Q THEN",
        f"    #AlarmId := {ALARM_EXTEND_TIMEOUT};",
        "ELSIF #TRetract.Q THEN",
        f"    #AlarmId := {ALARM_RETRACT_TIMEOUT};",
        "END_IF;",
        "#Fault := #AlarmId <> 0;",
        "#ActiveRequest := #Request;",
        "#Q_extend := #AllowsMotion AND NOT #Fault AND (#Request = 1);",
        "#Q_retract := #AllowsMotion AND NOT #Fault AND (#Request = 2);",
        "#Done := (#Q_extend AND #In_extended) OR (#Q_retract AND #In_retracted);",
        "#Busy := (#Q_extend OR #Q_retract) AND NOT #Done;",
        "#Ready := #AllowsMotion AND NOT #Busy AND NOT #Fault;",
        "#Blocked := ((#Mode = 0) AND (#Req_extend OR #Req_retract) OR (#Mode = 1) AND (#ManualRequest <> 0)) AND (#Request = 0);",
        "IF #Fault THEN",
        "    #State := 5;",
        "ELSIF #Q_extend AND NOT #In_extended THEN",
        "    #State := 1;",
        "ELSIF #Q_retract AND NOT #In_retracted THEN",
        "    #State := 2;",
        "ELSIF #In_extended THEN",
        "    #State := 3;",
        "ELSIF #In_retracted THEN",
        "    #State := 4;",
        "ELSE",
        "    #State := 0;",
        "END_IF;",
    ]:
        block.emit("    " + line)
    block.emit("END_FUNCTION_BLOCK")
    return block
