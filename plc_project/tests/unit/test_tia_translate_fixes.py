"""修复线 3(翻译层 scl.py)回归测试 — 内嵌真实 hr001 FlgNet 片段。

对应验证报告 ``docs/16-lad2scl-offline-validation.md`` §3/§4 的翻译层缺陷:

- S1  ``translate()`` 按部件身份/种类消费 fold 语句(不再顺序 ``next()``,
  不再错位借用/静默丢弃;CoilTON/数学框/SYS_TIME/T_CONV 均有发射分支)
- S2  scl.py 自身表达式机器:调用栈真环检测 + 记忆化复用,DAG 共享支路
  不再被替换成 ``"(* loop guard *)"`` 注释字面量
- S5  箱体 Q/ET/CV 与 S/R 线圈 out 作为 RLO 驱动(字符串版)
- S6  比较器 ``.pre`` 前置 RLO → ``(<pre> AND (a OP b))``(字符串版)
- S7  Convert/框 EN → ``IF <en> THEN … END_IF``(字符串版)
- S8  O 门 / PBox / Not 已折进下游表达式,translate 不再发 TODO 噪声

片段逐字节取自真实 TIA Portal V19 Openness 导出(DocumentInfo 2026-10-21,
工程 HR001_PLC_20260509.zap19)``PLC_Openness_data/hr001/export/plc/CPU_1200/blocks``:

- FB2009_NET1  005_Component_Cooling Fan_FB2009_CoolingFanFunction.xml 网络 1(SR 自锁+互锁+CoilTON)
- FC2300_NET5  006_ Visual Chiseling_FC2300 Time Calculation.xml 网络 5(Mul/Add 数学框)
- FB5002_NET1  001_KL_Standard_FB_FB5002_SafetyDoorV1.xml 网络 1(启保停+共享支路)
- FB1040_NET7  003_HomeStep_FB1040_HomePos.xml 网络 7(CoilTON×3+Gt+MOVE,23 条 fold 语句)
- FB1060_NET1  004_AutoStep_FB1060_AutoStep.xml 网络 1(IEC TON box+Eq .pre)
- FB5009_NET2  005_Component_FB5009_AnalOut.xml 网络 2(Convert EN)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agents.plc.tia.flgnet_fold import FoldStmt, fold_network
from agents.plc.tia.ir import AssignStmt, FoldedNetwork, Lit
from agents.plc.tia.scl import NetworkTranslator
from agents.plc.tia.simaticml import parse_block_xml

FB2009_NET1 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="Auto_Mode" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="22">
      <Symbol>
        <Component Name="I_StationToolOn_1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="23">
      <Symbol>
        <Component Name="I_StationToolOn_2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="Timer_StationToolOn" />
      </Symbol>
    </Access>
    <Access Scope="TypedConstant" UId="25">
      <Constant>
        <ConstantValue>T#2s</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="LocalVariable" UId="26">
      <Symbol>
        <Component Name="I_StationToolOn_1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="27">
      <Symbol>
        <Component Name="I_StationToolOn_2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="28">
      <Symbol>
        <Component Name="Timer_StationCoolingFan" />
        <Component Name="Q" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="29">
      <Symbol>
        <Component Name="Man_Mode" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="30">
      <Symbol>
        <Component Name="Emm_Mode" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="31">
      <Symbol>
        <Component Name="SR_StationTool" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="32">
      <Symbol>
        <Component Name="ToolAtPos" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="33">
      <Symbol>
        <Component Name="Timer_StationCoolingFan" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="34">
      <Symbol>
        <Component Name="CoolingTime" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="35" />
    <Part Name="Contact" UId="36" />
    <Part Name="Contact" UId="37" />
    <Part Name="CoilTON" UId="38">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="Contact" UId="39">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="40">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="41" />
    <Part Name="Contact" UId="42" />
    <Part Name="Contact" UId="43" />
    <Part Name="O" UId="44">
      <TemplateValue Name="Card" Type="Cardinality">5</TemplateValue>
    </Part>
    <Part Name="Sr" UId="45" />
    <Part Name="Coil" UId="46" />
    <Part Name="CoilTON" UId="47">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="48">
      <Powerrail />
      <NameCon UId="35" Name="in" />
      <NameCon UId="39" Name="in" />
      <NameCon UId="40" Name="in" />
      <NameCon UId="41" Name="in" />
      <NameCon UId="42" Name="in" />
      <NameCon UId="43" Name="in" />
    </Wire>
    <Wire UId="49">
      <IdentCon UId="21" />
      <NameCon UId="35" Name="operand" />
    </Wire>
    <Wire UId="50">
      <NameCon UId="35" Name="out" />
      <NameCon UId="36" Name="in" />
    </Wire>
    <Wire UId="51">
      <IdentCon UId="22" />
      <NameCon UId="36" Name="operand" />
    </Wire>
    <Wire UId="52">
      <NameCon UId="36" Name="out" />
      <NameCon UId="37" Name="in" />
    </Wire>
    <Wire UId="53">
      <IdentCon UId="23" />
      <NameCon UId="37" Name="operand" />
    </Wire>
    <Wire UId="54">
      <NameCon UId="37" Name="out" />
      <NameCon UId="38" Name="in" />
    </Wire>
    <Wire UId="55">
      <IdentCon UId="25" />
      <NameCon UId="38" Name="value" />
    </Wire>
    <Wire UId="56">
      <IdentCon UId="24" />
      <NameCon UId="38" Name="operand" />
    </Wire>
    <Wire UId="57">
      <NameCon UId="38" Name="out" />
      <NameCon UId="45" Name="s" />
    </Wire>
    <Wire UId="58">
      <IdentCon UId="26" />
      <NameCon UId="39" Name="operand" />
    </Wire>
    <Wire UId="59">
      <NameCon UId="39" Name="out" />
      <NameCon UId="44" Name="in1" />
    </Wire>
    <Wire UId="60">
      <IdentCon UId="27" />
      <NameCon UId="40" Name="operand" />
    </Wire>
    <Wire UId="61">
      <NameCon UId="40" Name="out" />
      <NameCon UId="44" Name="in2" />
    </Wire>
    <Wire UId="62">
      <IdentCon UId="28" />
      <NameCon UId="41" Name="operand" />
    </Wire>
    <Wire UId="63">
      <NameCon UId="41" Name="out" />
      <NameCon UId="44" Name="in3" />
    </Wire>
    <Wire UId="64">
      <IdentCon UId="29" />
      <NameCon UId="42" Name="operand" />
    </Wire>
    <Wire UId="65">
      <NameCon UId="42" Name="out" />
      <NameCon UId="44" Name="in4" />
    </Wire>
    <Wire UId="66">
      <IdentCon UId="30" />
      <NameCon UId="43" Name="operand" />
    </Wire>
    <Wire UId="67">
      <NameCon UId="43" Name="out" />
      <NameCon UId="44" Name="in5" />
    </Wire>
    <Wire UId="68">
      <NameCon UId="44" Name="out" />
      <NameCon UId="45" Name="r1" />
    </Wire>
    <Wire UId="69">
      <IdentCon UId="31" />
      <NameCon UId="45" Name="operand" />
    </Wire>
    <Wire UId="70">
      <NameCon UId="45" Name="q" />
      <NameCon UId="46" Name="in" />
      <NameCon UId="47" Name="in" />
    </Wire>
    <Wire UId="71">
      <IdentCon UId="32" />
      <NameCon UId="46" Name="operand" />
    </Wire>
    <Wire UId="72">
      <IdentCon UId="34" />
      <NameCon UId="47" Name="value" />
    </Wire>
    <Wire UId="73">
      <IdentCon UId="33" />
      <NameCon UId="47" Name="operand" />
    </Wire>
  </Wires>
</FlgNet>
"""

FC2300_NET5 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="High" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="22">
      <Symbol>
        <Component Name="DB2500 Visual Chiseling" />
        <Component Name="PLC Time" />
        <Component Name="MINUTE" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="23">
      <Constant>
        <ConstantType>USInt</ConstantType>
        <ConstantValue>64</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="Temp_PLC_Minute" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="25">
      <Symbol>
        <Component Name="Temp_PLC_Minute" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="26">
      <Symbol>
        <Component Name="DB2500 Visual Chiseling" />
        <Component Name="PLC Time" />
        <Component Name="SECOND" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="27">
      <Symbol>
        <Component Name="DB2100 Modbus Value" />
        <Component Name="PLC Para" />
        <Component Name="Time Word 2" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="28" />
    <Part Name="Mul" UId="29" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
    <Part Name="Add" UId="30" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
      <AutomaticTyped Name="SrcType" />
    </Part>
  </Parts>
  <Wires>
    <Wire UId="31">
      <Powerrail />
      <NameCon UId="28" Name="in" />
    </Wire>
    <Wire UId="32">
      <IdentCon UId="21" />
      <NameCon UId="28" Name="operand" />
    </Wire>
    <Wire UId="33">
      <NameCon UId="28" Name="out" />
      <NameCon UId="29" Name="en" />
    </Wire>
    <Wire UId="34">
      <IdentCon UId="22" />
      <NameCon UId="29" Name="in1" />
    </Wire>
    <Wire UId="35">
      <IdentCon UId="23" />
      <NameCon UId="29" Name="in2" />
    </Wire>
    <Wire UId="36">
      <NameCon UId="29" Name="eno" />
      <NameCon UId="30" Name="en" />
    </Wire>
    <Wire UId="37">
      <NameCon UId="29" Name="out" />
      <IdentCon UId="24" />
    </Wire>
    <Wire UId="38">
      <IdentCon UId="25" />
      <NameCon UId="30" Name="in1" />
    </Wire>
    <Wire UId="39">
      <IdentCon UId="26" />
      <NameCon UId="30" Name="in2" />
    </Wire>
    <Wire UId="40">
      <NameCon UId="30" Name="out" />
      <IdentCon UId="27" />
    </Wire>
  </Wires>
</FlgNet>
"""

FB5002_NET1 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="i_DoorOverRide" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="22">
      <Symbol>
        <Component Name="EMMode" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="23">
      <Symbol>
        <Component Name="i_AutoRunning" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="i_OpenDoorPmt" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="25">
      <Symbol>
        <Component Name="o_DoorOverRideRelayOn" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="26">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="27">
      <Symbol>
        <Component Name="o_DoorLockRelayON" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="28">
      <Symbol>
        <Component Name="DB1000_StdSignal" />
        <Component Name="PLS" />
        <Component Name="PS10" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="29">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="30">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="31">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT2" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="32">
      <Symbol>
        <Component Name="DB1000_StdSignal" />
        <Component Name="PLS" />
        <Component Name="PS10" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="33">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="34">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="DT1" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="35" />
    <Part Name="Contact" UId="36">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="37">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="38" />
    <Part Name="SCoil" UId="39" />
    <Part Name="Contact" UId="40" />
    <Part Name="RCoil" UId="41" />
    <Part Name="Contact" UId="42" />
    <Part Name="Contact" UId="43" />
    <Part Name="O" UId="44">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="Contact" UId="45" />
    <Part Name="Coil" UId="46" />
    <Part Name="Contact" UId="47" />
    <Part Name="Contact" UId="48" />
    <Part Name="O" UId="49">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="Coil" UId="50" />
  </Parts>
  <Wires>
    <Wire UId="51">
      <Powerrail />
      <NameCon UId="35" Name="in" />
    </Wire>
    <Wire UId="52">
      <IdentCon UId="21" />
      <NameCon UId="35" Name="operand" />
    </Wire>
    <Wire UId="53">
      <NameCon UId="35" Name="out" />
      <NameCon UId="36" Name="in" />
    </Wire>
    <Wire UId="54">
      <IdentCon UId="22" />
      <NameCon UId="36" Name="operand" />
    </Wire>
    <Wire UId="55">
      <NameCon UId="36" Name="out" />
      <NameCon UId="37" Name="in" />
    </Wire>
    <Wire UId="56">
      <IdentCon UId="23" />
      <NameCon UId="37" Name="operand" />
    </Wire>
    <Wire UId="57">
      <NameCon UId="37" Name="out" />
      <NameCon UId="38" Name="in" />
    </Wire>
    <Wire UId="58">
      <IdentCon UId="24" />
      <NameCon UId="38" Name="operand" />
    </Wire>
    <Wire UId="59">
      <NameCon UId="38" Name="out" />
      <NameCon UId="39" Name="in" />
      <NameCon UId="40" Name="in" />
      <NameCon UId="42" Name="in" />
      <NameCon UId="43" Name="in" />
      <NameCon UId="47" Name="in" />
      <NameCon UId="48" Name="in" />
    </Wire>
    <Wire UId="60">
      <IdentCon UId="25" />
      <NameCon UId="39" Name="operand" />
    </Wire>
    <Wire UId="61">
      <IdentCon UId="26" />
      <NameCon UId="40" Name="operand" />
    </Wire>
    <Wire UId="62">
      <NameCon UId="40" Name="out" />
      <NameCon UId="41" Name="in" />
    </Wire>
    <Wire UId="63">
      <IdentCon UId="27" />
      <NameCon UId="41" Name="operand" />
    </Wire>
    <Wire UId="64">
      <IdentCon UId="28" />
      <NameCon UId="42" Name="operand" />
    </Wire>
    <Wire UId="65">
      <NameCon UId="42" Name="out" />
      <NameCon UId="44" Name="in1" />
    </Wire>
    <Wire UId="66">
      <IdentCon UId="29" />
      <NameCon UId="43" Name="operand" />
    </Wire>
    <Wire UId="67">
      <NameCon UId="43" Name="out" />
      <NameCon UId="44" Name="in2" />
    </Wire>
    <Wire UId="68">
      <NameCon UId="44" Name="out" />
      <NameCon UId="45" Name="in" />
    </Wire>
    <Wire UId="69">
      <IdentCon UId="30" />
      <NameCon UId="45" Name="operand" />
    </Wire>
    <Wire UId="70">
      <NameCon UId="45" Name="out" />
      <NameCon UId="46" Name="in" />
    </Wire>
    <Wire UId="71">
      <IdentCon UId="31" />
      <NameCon UId="46" Name="operand" />
    </Wire>
    <Wire UId="72">
      <IdentCon UId="32" />
      <NameCon UId="47" Name="operand" />
    </Wire>
    <Wire UId="73">
      <NameCon UId="47" Name="out" />
      <NameCon UId="49" Name="in1" />
    </Wire>
    <Wire UId="74">
      <IdentCon UId="33" />
      <NameCon UId="48" Name="operand" />
    </Wire>
    <Wire UId="75">
      <NameCon UId="48" Name="out" />
      <NameCon UId="49" Name="in2" />
    </Wire>
    <Wire UId="76">
      <NameCon UId="49" Name="out" />
      <NameCon UId="50" Name="in" />
    </Wire>
    <Wire UId="77">
      <IdentCon UId="34" />
      <NameCon UId="50" Name="operand" />
    </Wire>
  </Wires>
</FlgNet>
"""

FB1040_NET7 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="LocalVariable" UId="21">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="S2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="22">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="S6" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="23">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="DrillMemory" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="24">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="GoHome" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="25">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>255</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="26">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="CTRL_IN" />
        <Component Name="ProgNo" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="27">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="DrillMemory" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="28">
      <Symbol>
        <Component Name="DB1081_ValveCall" />
        <Component Name="ST01" />
        <Component Name="Z05" />
        <Component Name="ExtAuto" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="29">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="ToolPowerOn" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="30">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="PowerOn_RetHome" />
      </Symbol>
    </Access>
    <Access Scope="TypedConstant" UId="31">
      <Constant>
        <ConstantValue>T#5S</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="32">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="PowerOn_RetHome" />
        <Component Name="Q" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="33">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="Current_2" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="34">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="CurrentMaxLimit" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="35">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="RetHomeHighCurrentOut" />
      </Symbol>
    </Access>
    <Access Scope="TypedConstant" UId="36">
      <Constant>
        <ConstantValue>T#100mS</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="37">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="RetHomeHighCurrentOut" />
        <Component Name="Q" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="38">
      <Symbol>
        <Component Name="DB1081_ValveCall" />
        <Component Name="ST01" />
        <Component Name="Z01" />
        <Component Name="RetAuto" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="39">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="DrillDirection3" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="40">
      <Symbol>
        <Component Name="DB1081_ValveCall" />
        <Component Name="ST01" />
        <Component Name="Z02" />
        <Component Name="RetAuto" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="41">
      <Symbol>
        <Component Name="QZ01RetEvt" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="42">
      <Symbol>
        <Component Name="IZ02RetPos" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="43">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="RetHome_Z02TimeOut" />
      </Symbol>
    </Access>
    <Access Scope="TypedConstant" UId="44">
      <Constant>
        <ConstantValue>T#5S</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="45">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="RetHome_Z02TimeOut" />
        <Component Name="Q" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="46">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="ErrEnd" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="47">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="Stop" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="48">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="RetHome_Z02RetTimeOut" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="49">
      <Symbol>
        <Component Name="IZ02RetPos" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="50">
      <Symbol>
        <Component Name="DB1081_ValveCall" />
        <Component Name="ST01" />
        <Component Name="Z02" />
        <Component Name="RetPos" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="51">
      <Symbol>
        <Component Name="IZ02RetPos" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="52">
      <Symbol>
        <Component Name="EdgeDetc" />
        <Component Name="JUMP" AccessModifier="Array">
          <Access Scope="LiteralConstant">
            <Constant>
              <ConstantType>DInt</ConstantType>
              <ConstantValue>3</ConstantValue>
            </Constant>
          </Access>
        </Component>
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="53">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="ProgStart" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="54">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="GoHome" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="55">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>255</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="56">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="CTRL_IN" />
        <Component Name="ProgNo" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="57">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>15</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="58">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="CTRL_IN" />
        <Component Name="RobotSpeed" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="59">
      <Symbol>
        <Component Name="EdgeDetc" />
        <Component Name="JUMP" AccessModifier="Array">
          <Access Scope="LiteralConstant">
            <Constant>
              <ConstantType>DInt</ConstantType>
              <ConstantValue>3</ConstantValue>
            </Constant>
          </Access>
        </Component>
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="60">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="Current_2" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="61">
      <Constant>
        <ConstantType>Real</ConstantType>
        <ConstantValue>0.5</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="LocalVariable" UId="62">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="ErrEnd" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="63">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="Stop" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="64">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="RetHome_PowerOff" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="65">
      <Symbol>
        <Component Name="DB1042_Timer" />
        <Component Name="RetHomeHighCurrentOut" />
        <Component Name="Q" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="66">
      <Symbol>
        <Component Name="EdgeDetc" />
        <Component Name="JUMP" AccessModifier="Array">
          <Access Scope="LiteralConstant">
            <Constant>
              <ConstantType>DInt</ConstantType>
              <ConstantValue>3</ConstantValue>
            </Constant>
          </Access>
        </Component>
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="67">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="Current_2" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="68">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="CurrentMaxLimit" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="69">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="ErrEnd" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="70">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="Stop" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="71">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="BitStuckErr_HighCurrent" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="72">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Status" />
        <Component Name="HomePos" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="73">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="S6" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="74">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="S6" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="75" />
    <Part Name="Contact" UId="76">
      <Negated Name="operand" />
    </Part>
    <Part Name="Contact" UId="77">
      <Negated Name="operand" />
    </Part>
    <Part Name="SCoil" UId="78" />
    <Part Name="Move" UId="79" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Contact" UId="80" />
    <Part Name="SCoil" UId="81" />
    <Part Name="Contact" UId="82" />
    <Part Name="CoilTON" UId="83">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="Contact" UId="84" />
    <Part Name="Gt" UId="85">
      <TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>
    </Part>
    <Part Name="CoilTON" UId="86">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="Contact" UId="87">
      <Negated Name="operand" />
    </Part>
    <Part Name="SCoil" UId="88" />
    <Part Name="Contact" UId="89" />
    <Part Name="SCoil" UId="90" />
    <Part Name="Contact" UId="91" />
    <Part Name="Contact" UId="92">
      <Negated Name="operand" />
    </Part>
    <Part Name="CoilTON" UId="93">
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="Contact" UId="94" />
    <Part Name="SCoil" UId="95" />
    <Part Name="SCoil" UId="96" />
    <Part Name="SCoil" UId="97" />
    <Part Name="Contact" UId="98" />
    <Part Name="Contact" UId="99" />
    <Part Name="Contact" UId="100" />
    <Part Name="O" UId="101">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="SCoil" UId="102" />
    <Part Name="SCoil" UId="103" />
    <Part Name="SCoil" UId="104" />
    <Part Name="Move" UId="105" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Move" UId="106" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Contact" UId="107" />
    <Part Name="Lt" UId="108">
      <TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>
    </Part>
    <Part Name="SCoil" UId="109" />
    <Part Name="SCoil" UId="110" />
    <Part Name="SCoil" UId="111" />
    <Part Name="Contact" UId="112" />
    <Part Name="Contact" UId="113" />
    <Part Name="Gt" UId="114">
      <TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>
    </Part>
    <Part Name="O" UId="115">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="SCoil" UId="116" />
    <Part Name="SCoil" UId="117" />
    <Part Name="SCoil" UId="118" />
    <Part Name="Contact" UId="119" />
    <Part Name="Contact" UId="120" />
    <Part Name="O" UId="121">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="Coil" UId="122" />
  </Parts>
  <Wires>
    <Wire UId="123">
      <Powerrail />
      <NameCon UId="75" Name="in" />
    </Wire>
    <Wire UId="124">
      <IdentCon UId="21" />
      <NameCon UId="75" Name="operand" />
    </Wire>
    <Wire UId="125">
      <NameCon UId="75" Name="out" />
      <NameCon UId="76" Name="in" />
      <NameCon UId="107" Name="in" />
      <NameCon UId="112" Name="in" />
      <NameCon UId="113" Name="in" />
      <NameCon UId="119" Name="in" />
      <NameCon UId="120" Name="in" />
    </Wire>
    <Wire UId="126">
      <IdentCon UId="22" />
      <NameCon UId="76" Name="operand" />
    </Wire>
    <Wire UId="127">
      <NameCon UId="76" Name="out" />
      <NameCon UId="77" Name="in" />
      <NameCon UId="80" Name="in" />
      <NameCon UId="106" Name="en" />
    </Wire>
    <Wire UId="128">
      <IdentCon UId="23" />
      <NameCon UId="77" Name="operand" />
    </Wire>
    <Wire UId="129">
      <NameCon UId="77" Name="out" />
      <NameCon UId="78" Name="in" />
    </Wire>
    <Wire UId="130">
      <IdentCon UId="24" />
      <NameCon UId="78" Name="operand" />
    </Wire>
    <Wire UId="131">
      <NameCon UId="78" Name="out" />
      <NameCon UId="79" Name="en" />
    </Wire>
    <Wire UId="132">
      <IdentCon UId="25" />
      <NameCon UId="79" Name="in" />
    </Wire>
    <Wire UId="133">
      <NameCon UId="79" Name="out1" />
      <IdentCon UId="26" />
    </Wire>
    <Wire UId="134">
      <IdentCon UId="27" />
      <NameCon UId="80" Name="operand" />
    </Wire>
    <Wire UId="135">
      <NameCon UId="80" Name="out" />
      <NameCon UId="81" Name="in" />
      <NameCon UId="82" Name="in" />
      <NameCon UId="84" Name="in" />
    </Wire>
    <Wire UId="136">
      <IdentCon UId="28" />
      <NameCon UId="81" Name="operand" />
    </Wire>
    <Wire UId="137">
      <IdentCon UId="29" />
      <NameCon UId="82" Name="operand" />
    </Wire>
    <Wire UId="138">
      <NameCon UId="82" Name="out" />
      <NameCon UId="83" Name="in" />
    </Wire>
    <Wire UId="139">
      <IdentCon UId="31" />
      <NameCon UId="83" Name="value" />
    </Wire>
    <Wire UId="140">
      <IdentCon UId="30" />
      <NameCon UId="83" Name="operand" />
    </Wire>
    <Wire UId="141">
      <IdentCon UId="32" />
      <NameCon UId="84" Name="operand" />
    </Wire>
    <Wire UId="142">
      <NameCon UId="84" Name="out" />
      <NameCon UId="85" Name="pre" />
      <NameCon UId="87" Name="in" />
      <NameCon UId="91" Name="in" />
      <NameCon UId="94" Name="in" />
      <NameCon UId="98" Name="in" />
    </Wire>
    <Wire UId="143">
      <IdentCon UId="33" />
      <NameCon UId="85" Name="in1" />
    </Wire>
    <Wire UId="144">
      <IdentCon UId="34" />
      <NameCon UId="85" Name="in2" />
    </Wire>
    <Wire UId="145">
      <NameCon UId="85" Name="out" />
      <NameCon UId="86" Name="in" />
    </Wire>
    <Wire UId="146">
      <IdentCon UId="36" />
      <NameCon UId="86" Name="value" />
    </Wire>
    <Wire UId="147">
      <IdentCon UId="35" />
      <NameCon UId="86" Name="operand" />
    </Wire>
    <Wire UId="148">
      <IdentCon UId="37" />
      <NameCon UId="87" Name="operand" />
    </Wire>
    <Wire UId="149">
      <NameCon UId="87" Name="out" />
      <NameCon UId="88" Name="in" />
      <NameCon UId="89" Name="in" />
    </Wire>
    <Wire UId="150">
      <IdentCon UId="38" />
      <NameCon UId="88" Name="operand" />
    </Wire>
    <Wire UId="151">
      <IdentCon UId="39" />
      <NameCon UId="89" Name="operand" />
    </Wire>
    <Wire UId="152">
      <NameCon UId="89" Name="out" />
      <NameCon UId="90" Name="in" />
    </Wire>
    <Wire UId="153">
      <IdentCon UId="40" />
      <NameCon UId="90" Name="operand" />
    </Wire>
    <Wire UId="154">
      <IdentCon UId="41" />
      <NameCon UId="91" Name="operand" />
    </Wire>
    <Wire UId="155">
      <NameCon UId="91" Name="out" />
      <NameCon UId="92" Name="in" />
    </Wire>
    <Wire UId="156">
      <IdentCon UId="42" />
      <NameCon UId="92" Name="operand" />
    </Wire>
    <Wire UId="157">
      <NameCon UId="92" Name="out" />
      <NameCon UId="93" Name="in" />
    </Wire>
    <Wire UId="158">
      <IdentCon UId="44" />
      <NameCon UId="93" Name="value" />
    </Wire>
    <Wire UId="159">
      <IdentCon UId="43" />
      <NameCon UId="93" Name="operand" />
    </Wire>
    <Wire UId="160">
      <IdentCon UId="45" />
      <NameCon UId="94" Name="operand" />
    </Wire>
    <Wire UId="161">
      <NameCon UId="94" Name="out" />
      <NameCon UId="95" Name="in" />
    </Wire>
    <Wire UId="162">
      <IdentCon UId="46" />
      <NameCon UId="95" Name="operand" />
    </Wire>
    <Wire UId="163">
      <NameCon UId="95" Name="out" />
      <NameCon UId="96" Name="in" />
    </Wire>
    <Wire UId="164">
      <IdentCon UId="47" />
      <NameCon UId="96" Name="operand" />
    </Wire>
    <Wire UId="165">
      <NameCon UId="96" Name="out" />
      <NameCon UId="97" Name="in" />
    </Wire>
    <Wire UId="166">
      <IdentCon UId="48" />
      <NameCon UId="97" Name="operand" />
    </Wire>
    <Wire UId="167">
      <IdentCon UId="49" />
      <NameCon UId="98" Name="operand" />
    </Wire>
    <Wire UId="168">
      <NameCon UId="98" Name="out" />
      <NameCon UId="99" Name="in" />
      <NameCon UId="100" Name="in" />
    </Wire>
    <Wire UId="169">
      <IdentCon UId="50" />
      <NameCon UId="99" Name="operand" />
    </Wire>
    <Wire UId="170">
      <NameCon UId="99" Name="out" />
      <NameCon UId="101" Name="in1" />
    </Wire>
    <Wire UId="171">
      <IdentCon UId="51" />
      <NameCon UId="100" Name="operand" />
    </Wire>
    <Wire UId="172">
      <NameCon UId="100" Name="out" />
      <NameCon UId="101" Name="in2" />
    </Wire>
    <Wire UId="173">
      <NameCon UId="101" Name="out" />
      <NameCon UId="102" Name="in" />
    </Wire>
    <Wire UId="174">
      <IdentCon UId="52" />
      <NameCon UId="102" Name="operand" />
    </Wire>
    <Wire UId="175">
      <NameCon UId="102" Name="out" />
      <NameCon UId="103" Name="in" />
    </Wire>
    <Wire UId="176">
      <IdentCon UId="53" />
      <NameCon UId="103" Name="operand" />
    </Wire>
    <Wire UId="177">
      <NameCon UId="103" Name="out" />
      <NameCon UId="104" Name="in" />
    </Wire>
    <Wire UId="178">
      <IdentCon UId="54" />
      <NameCon UId="104" Name="operand" />
    </Wire>
    <Wire UId="179">
      <NameCon UId="104" Name="out" />
      <NameCon UId="105" Name="en" />
    </Wire>
    <Wire UId="180">
      <IdentCon UId="55" />
      <NameCon UId="105" Name="in" />
    </Wire>
    <Wire UId="181">
      <NameCon UId="105" Name="out1" />
      <IdentCon UId="56" />
    </Wire>
    <Wire UId="182">
      <IdentCon UId="57" />
      <NameCon UId="106" Name="in" />
    </Wire>
    <Wire UId="183">
      <NameCon UId="106" Name="out1" />
      <IdentCon UId="58" />
    </Wire>
    <Wire UId="184">
      <IdentCon UId="59" />
      <NameCon UId="107" Name="operand" />
    </Wire>
    <Wire UId="185">
      <NameCon UId="107" Name="out" />
      <NameCon UId="108" Name="pre" />
    </Wire>
    <Wire UId="186">
      <IdentCon UId="60" />
      <NameCon UId="108" Name="in1" />
    </Wire>
    <Wire UId="187">
      <IdentCon UId="61" />
      <NameCon UId="108" Name="in2" />
    </Wire>
    <Wire UId="188">
      <NameCon UId="108" Name="out" />
      <NameCon UId="109" Name="in" />
    </Wire>
    <Wire UId="189">
      <IdentCon UId="62" />
      <NameCon UId="109" Name="operand" />
    </Wire>
    <Wire UId="190">
      <NameCon UId="109" Name="out" />
      <NameCon UId="110" Name="in" />
    </Wire>
    <Wire UId="191">
      <IdentCon UId="63" />
      <NameCon UId="110" Name="operand" />
    </Wire>
    <Wire UId="192">
      <NameCon UId="110" Name="out" />
      <NameCon UId="111" Name="in" />
    </Wire>
    <Wire UId="193">
      <IdentCon UId="64" />
      <NameCon UId="111" Name="operand" />
    </Wire>
    <Wire UId="194">
      <IdentCon UId="65" />
      <NameCon UId="112" Name="operand" />
    </Wire>
    <Wire UId="195">
      <NameCon UId="112" Name="out" />
      <NameCon UId="115" Name="in1" />
    </Wire>
    <Wire UId="196">
      <IdentCon UId="66" />
      <NameCon UId="113" Name="operand" />
    </Wire>
    <Wire UId="197">
      <NameCon UId="113" Name="out" />
      <NameCon UId="114" Name="pre" />
    </Wire>
    <Wire UId="198">
      <IdentCon UId="67" />
      <NameCon UId="114" Name="in1" />
    </Wire>
    <Wire UId="199">
      <IdentCon UId="68" />
      <NameCon UId="114" Name="in2" />
    </Wire>
    <Wire UId="200">
      <NameCon UId="114" Name="out" />
      <NameCon UId="115" Name="in2" />
    </Wire>
    <Wire UId="201">
      <NameCon UId="115" Name="out" />
      <NameCon UId="116" Name="in" />
    </Wire>
    <Wire UId="202">
      <IdentCon UId="69" />
      <NameCon UId="116" Name="operand" />
    </Wire>
    <Wire UId="203">
      <NameCon UId="116" Name="out" />
      <NameCon UId="117" Name="in" />
    </Wire>
    <Wire UId="204">
      <IdentCon UId="70" />
      <NameCon UId="117" Name="operand" />
    </Wire>
    <Wire UId="205">
      <NameCon UId="117" Name="out" />
      <NameCon UId="118" Name="in" />
    </Wire>
    <Wire UId="206">
      <IdentCon UId="71" />
      <NameCon UId="118" Name="operand" />
    </Wire>
    <Wire UId="207">
      <IdentCon UId="72" />
      <NameCon UId="119" Name="operand" />
    </Wire>
    <Wire UId="208">
      <NameCon UId="119" Name="out" />
      <NameCon UId="121" Name="in1" />
    </Wire>
    <Wire UId="209">
      <IdentCon UId="73" />
      <NameCon UId="120" Name="operand" />
    </Wire>
    <Wire UId="210">
      <NameCon UId="120" Name="out" />
      <NameCon UId="121" Name="in2" />
    </Wire>
    <Wire UId="211">
      <NameCon UId="121" Name="out" />
      <NameCon UId="122" Name="in" />
    </Wire>
    <Wire UId="212">
      <IdentCon UId="74" />
      <NameCon UId="122" Name="operand" />
    </Wire>
  </Wires>
</FlgNet>
"""

FB1060_NET1 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="GlobalVariable" UId="21">
      <Symbol>
        <Component Name="TRUE" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="22">
      <Symbol>
        <Component Name="StepMode_M" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="23">
      <Symbol>
        <Component Name="DB1001_SysMode" />
        <Component Name="SubSysMode" />
        <Component Name="Mode" />
        <Component Name="StepPls" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="MainStep" />
        <Component Name="StartCmd_ManMode" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="25">
      <Symbol>
        <Component Name="ManMode_M" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="26">
      <Symbol>
        <Component Name="AutoMode_M" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="27">
      <Symbol>
        <Component Name="StepPls" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="28">
      <Symbol>
        <Component Name="AllMode_M" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="29">
      <Symbol>
        <Component Name="DB1081_ValveCall" />
        <Component Name="ST01" />
        <Component Name="Z08" />
        <Component Name="RetAuto" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="30">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="EmmMode" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="31">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="PcErr" />
      </Symbol>
    </Access>
    <Access Scope="TypedConstant" UId="32">
      <Constant>
        <ConstantValue>T#5s</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="33">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="PowerOff" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="34">
      <Symbol>
        <Component Name="DB1060_AutoStep" />
        <Component Name="EdgeDetc" />
        <Component Name="Pulse" AccessModifier="Array">
          <Access Scope="LiteralConstant">
            <Constant>
              <ConstantType>DInt</ConstantType>
              <ConstantValue>10</ConstantValue>
            </Constant>
          </Access>
        </Component>
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="35">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="Cmd" />
        <Component Name="Auto" />
        <Component Name="Stop" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="36">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>0</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="37">
      <Symbol>
        <Component Name="DB1080_Component" />
        <Component Name="Robot" />
        <Component Name="CTRL_IN" />
        <Component Name="ProgNo" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="38">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="PosNoClear" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="39">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="ClearHoleNoReq" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="40">
      <Symbol>
        <Component Name="DB720_KuKa_MainCtrl" />
        <Component Name="CmdOut" />
        <Component Name="gi_ToolTypeNo" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="41">
      <Constant>
        <ConstantType>Byte</ConstantType>
        <ConstantValue>2</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="42">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="ChangeTool" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="43">
      <Constant>
        <ConstantType>Int</ConstantType>
        <ConstantValue>0</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="LocalVariable" UId="44">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="HoleNo" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="45">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="HoleNo" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="46">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="PosNo" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="47">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="HoleNo" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="48">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="HoleNo" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="49">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Recv" />
        <Component Name="ClearHoleNoReq" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="50">
      <Symbol>
        <Component Name="Aux" />
        <Component Name="HoleNo" />
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="51">
      <Constant>
        <ConstantType>Int</ConstantType>
        <ConstantValue>0</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="52">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="ClearHoleNum" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="53">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="DrillDirection1" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="54">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="DrillDirection3" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="55">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Para" />
        <Component Name="Auto_Force" AccessModifier="Array">
          <Access Scope="LiteralConstant">
            <Constant>
              <ConstantType>DInt</ConstantType>
              <ConstantValue>5</ConstantValue>
            </Constant>
          </Access>
        </Component>
      </Symbol>
    </Access>
    <Access Scope="LiteralConstant" UId="56">
      <Constant>
        <ConstantType>Real</ConstantType>
        <ConstantValue>0.0</ConstantValue>
      </Constant>
    </Access>
    <Access Scope="GlobalVariable" UId="57">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="ForceCannotZero" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="58">
      <Symbol>
        <Component Name="ManMode_M" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="59">
      <Symbol>
        <Component Name="ErrRst_M" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="60">
      <Symbol>
        <Component Name="DB1900_Communication_PC" />
        <Component Name="Send" />
        <Component Name="PowerOff" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="61">
      <Symbol>
        <Component Name="DB1147_PromptStartNotPmt" />
        <Component Name="Public" />
        <Component Name="ParaWiriteOuttime" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="62">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="BitStuckErr_Fixture" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="63">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="BitStuckErr_HighCurrent" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="64">
      <Symbol>
        <Component Name="DB1148_PromptBeeper" />
        <Component Name="Public" />
        <Component Name="DiamondCoreNOK" />
      </Symbol>
    </Access>
    <Access Scope="GlobalVariable" UId="65">
      <Symbol>
        <Component Name="DB1147_PromptStartNotPmt" />
        <Component Name="Public" />
        <Component Name="PcCommErr" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="66" />
    <Part Name="Contact" UId="67" />
    <Part Name="Contact" UId="68" />
    <Part Name="Contact" UId="69" />
    <Part Name="Contact" UId="70" />
    <Part Name="Contact" UId="71" />
    <Part Name="O" UId="72">
      <TemplateValue Name="Card" Type="Cardinality">4</TemplateValue>
    </Part>
    <Part Name="Coil" UId="73" />
    <Part Name="Contact" UId="74">
      <Negated Name="operand" />
    </Part>
    <Part Name="SCoil" UId="75" />
    <Part Name="Contact" UId="76" />
    <Part Name="Coil" UId="77" />
    <Part Name="TON" Version="1.0" UId="78">
      <Instance Scope="GlobalVariable" UId="79">
        <Component Name="Timer_RecvEmmMode" />
      </Instance>
      <TemplateValue Name="time_type" Type="Type">Time</TemplateValue>
    </Part>
    <Part Name="SCoil" UId="80" />
    <Part Name="PBox" UId="81" />
    <Part Name="SCoil" UId="82" />
    <Part Name="Move" UId="83" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Contact" UId="84" />
    <Part Name="Contact" UId="85" />
    <Part Name="Eq" UId="86">
      <TemplateValue Name="SrcType" Type="Type">Byte</TemplateValue>
    </Part>
    <Part Name="Contact" UId="87" />
    <Part Name="O" UId="88">
      <TemplateValue Name="Card" Type="Cardinality">3</TemplateValue>
    </Part>
    <Part Name="Move" UId="89" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Move" UId="90" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Move" UId="91" DisabledENO="true">
      <TemplateValue Name="Card" Type="Cardinality">1</TemplateValue>
    </Part>
    <Part Name="Contact" UId="92" />
    <Part Name="Eq" UId="93">
      <TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>
    </Part>
    <Part Name="Coil" UId="94" />
    <Part Name="Contact" UId="95" />
    <Part Name="Contact" UId="96" />
    <Part Name="O" UId="97">
      <TemplateValue Name="Card" Type="Cardinality">2</TemplateValue>
    </Part>
    <Part Name="Eq" UId="98">
      <TemplateValue Name="SrcType" Type="Type">Real</TemplateValue>
    </Part>
    <Part Name="Coil" UId="99" />
    <Part Name="Contact" UId="100" />
    <Part Name="Contact" UId="101" />
    <Part Name="RCoil" UId="102" />
    <Part Name="RCoil" UId="103" />
    <Part Name="RCoil" UId="104" />
    <Part Name="RCoil" UId="105" />
    <Part Name="RCoil" UId="106" />
    <Part Name="RCoil" UId="107" />
  </Parts>
  <Wires>
    <Wire UId="109">
      <Powerrail />
      <NameCon UId="66" Name="in" />
    </Wire>
    <Wire UId="110">
      <IdentCon UId="21" />
      <NameCon UId="66" Name="operand" />
    </Wire>
    <Wire UId="111">
      <NameCon UId="66" Name="out" />
      <NameCon UId="67" Name="in" />
      <NameCon UId="70" Name="in" />
      <NameCon UId="71" Name="in" />
      <NameCon UId="74" Name="in" />
      <NameCon UId="76" Name="in" />
      <NameCon UId="84" Name="in" />
      <NameCon UId="85" Name="in" />
      <NameCon UId="86" Name="pre" />
      <NameCon UId="90" Name="en" />
      <NameCon UId="92" Name="in" />
      <NameCon UId="95" Name="in" />
      <NameCon UId="96" Name="in" />
      <NameCon UId="100" Name="in" />
    </Wire>
    <Wire UId="112">
      <IdentCon UId="22" />
      <NameCon UId="67" Name="operand" />
    </Wire>
    <Wire UId="113">
      <NameCon UId="67" Name="out" />
      <NameCon UId="68" Name="in" />
      <NameCon UId="69" Name="in" />
    </Wire>
    <Wire UId="114">
      <IdentCon UId="23" />
      <NameCon UId="68" Name="operand" />
    </Wire>
    <Wire UId="115">
      <NameCon UId="68" Name="out" />
      <NameCon UId="72" Name="in1" />
    </Wire>
    <Wire UId="116">
      <IdentCon UId="24" />
      <NameCon UId="69" Name="operand" />
    </Wire>
    <Wire UId="117">
      <NameCon UId="69" Name="out" />
      <NameCon UId="72" Name="in2" />
    </Wire>
    <Wire UId="118">
      <IdentCon UId="25" />
      <NameCon UId="70" Name="operand" />
    </Wire>
    <Wire UId="119">
      <NameCon UId="70" Name="out" />
      <NameCon UId="72" Name="in3" />
    </Wire>
    <Wire UId="120">
      <IdentCon UId="26" />
      <NameCon UId="71" Name="operand" />
    </Wire>
    <Wire UId="121">
      <NameCon UId="71" Name="out" />
      <NameCon UId="72" Name="in4" />
    </Wire>
    <Wire UId="122">
      <NameCon UId="72" Name="out" />
      <NameCon UId="73" Name="in" />
    </Wire>
    <Wire UId="123">
      <IdentCon UId="27" />
      <NameCon UId="73" Name="operand" />
    </Wire>
    <Wire UId="124">
      <IdentCon UId="28" />
      <NameCon UId="74" Name="operand" />
    </Wire>
    <Wire UId="125">
      <NameCon UId="74" Name="out" />
      <NameCon UId="75" Name="in" />
    </Wire>
    <Wire UId="126">
      <IdentCon UId="29" />
      <NameCon UId="75" Name="operand" />
    </Wire>
    <Wire UId="127">
      <IdentCon UId="30" />
      <NameCon UId="76" Name="operand" />
    </Wire>
    <Wire UId="128">
      <NameCon UId="76" Name="out" />
      <NameCon UId="77" Name="in" />
      <NameCon UId="78" Name="IN" />
      <NameCon UId="81" Name="in" />
    </Wire>
    <Wire UId="129">
      <IdentCon UId="31" />
      <NameCon UId="77" Name="operand" />
    </Wire>
    <Wire UId="130">
      <IdentCon UId="32" />
      <NameCon UId="78" Name="PT" />
    </Wire>
    <Wire UId="131">
      <NameCon UId="78" Name="Q" />
      <NameCon UId="80" Name="in" />
    </Wire>
    <Wire UId="132">
      <NameCon UId="78" Name="ET" />
      <OpenCon UId="108" />
    </Wire>
    <Wire UId="133">
      <IdentCon UId="33" />
      <NameCon UId="80" Name="operand" />
    </Wire>
    <Wire UId="134">
      <IdentCon UId="34" />
      <NameCon UId="81" Name="bit" />
    </Wire>
    <Wire UId="135">
      <NameCon UId="81" Name="out" />
      <NameCon UId="82" Name="in" />
    </Wire>
    <Wire UId="136">
      <IdentCon UId="35" />
      <NameCon UId="82" Name="operand" />
    </Wire>
    <Wire UId="137">
      <NameCon UId="82" Name="out" />
      <NameCon UId="83" Name="en" />
    </Wire>
    <Wire UId="138">
      <IdentCon UId="36" />
      <NameCon UId="83" Name="in" />
    </Wire>
    <Wire UId="139">
      <NameCon UId="83" Name="out1" />
      <IdentCon UId="37" />
    </Wire>
    <Wire UId="140">
      <IdentCon UId="38" />
      <NameCon UId="84" Name="operand" />
    </Wire>
    <Wire UId="141">
      <NameCon UId="84" Name="out" />
      <NameCon UId="88" Name="in1" />
    </Wire>
    <Wire UId="142">
      <IdentCon UId="39" />
      <NameCon UId="85" Name="operand" />
    </Wire>
    <Wire UId="143">
      <NameCon UId="85" Name="out" />
      <NameCon UId="88" Name="in2" />
    </Wire>
    <Wire UId="144">
      <IdentCon UId="40" />
      <NameCon UId="86" Name="in1" />
    </Wire>
    <Wire UId="145">
      <IdentCon UId="41" />
      <NameCon UId="86" Name="in2" />
    </Wire>
    <Wire UId="146">
      <NameCon UId="86" Name="out" />
      <NameCon UId="87" Name="in" />
    </Wire>
    <Wire UId="147">
      <IdentCon UId="42" />
      <NameCon UId="87" Name="operand" />
    </Wire>
    <Wire UId="148">
      <NameCon UId="87" Name="out" />
      <NameCon UId="88" Name="in3" />
    </Wire>
    <Wire UId="149">
      <NameCon UId="88" Name="out" />
      <NameCon UId="89" Name="en" />
    </Wire>
    <Wire UId="150">
      <IdentCon UId="43" />
      <NameCon UId="89" Name="in" />
    </Wire>
    <Wire UId="151">
      <NameCon UId="89" Name="out1" />
      <IdentCon UId="44" />
    </Wire>
    <Wire UId="152">
      <IdentCon UId="45" />
      <NameCon UId="90" Name="in" />
    </Wire>
    <Wire UId="153">
      <NameCon UId="90" Name="eno" />
      <NameCon UId="91" Name="en" />
    </Wire>
    <Wire UId="154">
      <NameCon UId="90" Name="out1" />
      <IdentCon UId="46" />
    </Wire>
    <Wire UId="155">
      <IdentCon UId="47" />
      <NameCon UId="91" Name="in" />
    </Wire>
    <Wire UId="156">
      <NameCon UId="91" Name="out1" />
      <IdentCon UId="48" />
    </Wire>
    <Wire UId="157">
      <IdentCon UId="49" />
      <NameCon UId="92" Name="operand" />
    </Wire>
    <Wire UId="158">
      <NameCon UId="92" Name="out" />
      <NameCon UId="93" Name="pre" />
    </Wire>
    <Wire UId="159">
      <IdentCon UId="50" />
      <NameCon UId="93" Name="in1" />
    </Wire>
    <Wire UId="160">
      <IdentCon UId="51" />
      <NameCon UId="93" Name="in2" />
    </Wire>
    <Wire UId="161">
      <NameCon UId="93" Name="out" />
      <NameCon UId="94" Name="in" />
    </Wire>
    <Wire UId="162">
      <IdentCon UId="52" />
      <NameCon UId="94" Name="operand" />
    </Wire>
    <Wire UId="163">
      <IdentCon UId="53" />
      <NameCon UId="95" Name="operand" />
    </Wire>
    <Wire UId="164">
      <NameCon UId="95" Name="out" />
      <NameCon UId="97" Name="in1" />
    </Wire>
    <Wire UId="165">
      <IdentCon UId="54" />
      <NameCon UId="96" Name="operand" />
    </Wire>
    <Wire UId="166">
      <NameCon UId="96" Name="out" />
      <NameCon UId="97" Name="in2" />
    </Wire>
    <Wire UId="167">
      <NameCon UId="97" Name="out" />
      <NameCon UId="98" Name="pre" />
    </Wire>
    <Wire UId="168">
      <IdentCon UId="55" />
      <NameCon UId="98" Name="in1" />
    </Wire>
    <Wire UId="169">
      <IdentCon UId="56" />
      <NameCon UId="98" Name="in2" />
    </Wire>
    <Wire UId="170">
      <NameCon UId="98" Name="out" />
      <NameCon UId="99" Name="in" />
    </Wire>
    <Wire UId="171">
      <IdentCon UId="57" />
      <NameCon UId="99" Name="operand" />
    </Wire>
    <Wire UId="172">
      <IdentCon UId="58" />
      <NameCon UId="100" Name="operand" />
    </Wire>
    <Wire UId="173">
      <NameCon UId="100" Name="out" />
      <NameCon UId="101" Name="in" />
    </Wire>
    <Wire UId="174">
      <IdentCon UId="59" />
      <NameCon UId="101" Name="operand" />
    </Wire>
    <Wire UId="175">
      <NameCon UId="101" Name="out" />
      <NameCon UId="102" Name="in" />
      <NameCon UId="104" Name="in" />
      <NameCon UId="106" Name="in" />
    </Wire>
    <Wire UId="176">
      <IdentCon UId="60" />
      <NameCon UId="102" Name="operand" />
    </Wire>
    <Wire UId="177">
      <NameCon UId="102" Name="out" />
      <NameCon UId="103" Name="in" />
    </Wire>
    <Wire UId="178">
      <IdentCon UId="61" />
      <NameCon UId="103" Name="operand" />
    </Wire>
    <Wire UId="179">
      <IdentCon UId="62" />
      <NameCon UId="104" Name="operand" />
    </Wire>
    <Wire UId="180">
      <NameCon UId="104" Name="out" />
      <NameCon UId="105" Name="in" />
    </Wire>
    <Wire UId="181">
      <IdentCon UId="63" />
      <NameCon UId="105" Name="operand" />
    </Wire>
    <Wire UId="182">
      <IdentCon UId="64" />
      <NameCon UId="106" Name="operand" />
    </Wire>
    <Wire UId="183">
      <NameCon UId="106" Name="out" />
      <NameCon UId="107" Name="in" />
    </Wire>
    <Wire UId="184">
      <IdentCon UId="65" />
      <NameCon UId="107" Name="operand" />
    </Wire>
  </Wires>
</FlgNet>
"""

FB5009_NET2 = """
<FlgNet xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/FlgNet/v5">
  <Parts>
    <Access Scope="GlobalVariable" UId="21">
      <Symbol>
        <Component Name="TRUE" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="22">
      <Symbol>
        <Component Name="Cmd" />
        <Component Name="Read1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="23">
      <Symbol>
        <Component Name="IW" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="24">
      <Symbol>
        <Component Name="Ctrl_IN" />
        <Component Name="TP_ActualAI_1" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="25">
      <Symbol>
        <Component Name="Cmd" />
        <Component Name="Read2" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="26">
      <Symbol>
        <Component Name="IW" />
      </Symbol>
    </Access>
    <Access Scope="LocalVariable" UId="27">
      <Symbol>
        <Component Name="Ctrl_IN" />
        <Component Name="TP_ActualAI_2" />
      </Symbol>
    </Access>
    <Part Name="Contact" UId="28" />
    <Part Name="Contact" UId="29" />
    <Part Name="Convert" UId="30" DisabledENO="true">
      <TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>
      <TemplateValue Name="DestType" Type="Type">Real</TemplateValue>
    </Part>
    <Part Name="Contact" UId="31" />
    <Part Name="Convert" UId="32" DisabledENO="true">
      <TemplateValue Name="SrcType" Type="Type">Int</TemplateValue>
      <TemplateValue Name="DestType" Type="Type">Real</TemplateValue>
    </Part>
  </Parts>
  <Wires>
    <Wire UId="33">
      <Powerrail />
      <NameCon UId="28" Name="in" />
    </Wire>
    <Wire UId="34">
      <IdentCon UId="21" />
      <NameCon UId="28" Name="operand" />
    </Wire>
    <Wire UId="35">
      <NameCon UId="28" Name="out" />
      <NameCon UId="29" Name="in" />
      <NameCon UId="31" Name="in" />
    </Wire>
    <Wire UId="36">
      <IdentCon UId="22" />
      <NameCon UId="29" Name="operand" />
    </Wire>
    <Wire UId="37">
      <NameCon UId="29" Name="out" />
      <NameCon UId="30" Name="en" />
    </Wire>
    <Wire UId="38">
      <IdentCon UId="23" />
      <NameCon UId="30" Name="in" />
    </Wire>
    <Wire UId="39">
      <NameCon UId="30" Name="out" />
      <IdentCon UId="24" />
    </Wire>
    <Wire UId="40">
      <IdentCon UId="25" />
      <NameCon UId="31" Name="operand" />
    </Wire>
    <Wire UId="41">
      <NameCon UId="31" Name="out" />
      <NameCon UId="32" Name="en" />
    </Wire>
    <Wire UId="42">
      <IdentCon UId="26" />
      <NameCon UId="32" Name="in" />
    </Wire>
    <Wire UId="43">
      <NameCon UId="32" Name="out" />
      <IdentCon UId="27" />
    </Wire>
  </Wires>
</FlgNet>
"""


def _parse_fragment(flgnet: str):
    """Parse one real FlgNet fragment embedded in a minimal LAD FB document."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<Document>\n'
        '  <SW.Blocks.FB ID="0">\n'
        '    <AttributeList><Name>FB_Frag</Name><Number>99</Number>\n'
        "      <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        "    </AttributeList>\n"
        '    <ObjectList>\n'
        '      <SW.Blocks.CompileUnit ID="5" CompositionName="CompileUnits">\n'
        "        <AttributeList>\n"
        f"          <NetworkSource>{flgnet}</NetworkSource>\n"
        "          <ProgrammingLanguage>LAD</ProgrammingLanguage>\n"
        "        </AttributeList>\n"
        "      </SW.Blocks.CompileUnit>\n"
        "    </ObjectList>\n"
        "  </SW.Blocks.FB>\n"
        "</Document>\n"
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "frag.xml"
        path.write_text(xml, encoding="utf-8")
        return parse_block_xml(path)


def _translate(flgnet: str, *, fold: bool = True) -> list[str]:
    """Translate the fragment's single network.

    ``fold=True`` 镜像管线(folded 语句已挂载 → translate 消费路径);
    ``fold=False`` 不挂载 folded → 走 scl.py 自身发射路径(字符串版机器)。
    """
    block = _parse_fragment(flgnet)
    network = block.networks[0]
    if fold:
        network.folded = fold_network(network)
    return NetworkTranslator(block, network).translate()


# ---------------------------------------------------------------------------
# S1 — fold 语句按身份/种类消费:不再错位、不再丢失
# ---------------------------------------------------------------------------


def test_fb2009_net1_all_four_statements_complete() -> None:
    """报告 §3.1 FB2009 网络 1:TON 调用、SR 调用、ToolAtPos 线圈、第二 TON。

    修复前:CoilTON 只发 TODO 不消费 → Sr 错位拿到 TON 语句、Coil 拿到
    ``Sr();``、第二 TON 整条丢弃。
    """
    stmts = _translate(FB2009_NET1)
    assert len(stmts) == 4
    joined = "\n".join(stmts)
    assert "TODO" not in joined
    # ① CoilTON → 定时器调用(IN 链 + PT 常量)
    assert "#Timer_StationToolOn.TON(IN :=" in stmts[0]
    assert "#Auto_Mode" in stmts[0] and "#I_StationToolOn_1" in stmts[0]
    assert "PT:=T#2s" in stmts[0].replace(" ", "")
    # ② SR 调用:S 由 TON.Q 驱动,R1 为五支路互锁
    assert "#SR_StationTool.SR(" in stmts[1]
    assert "S := #Timer_StationToolOn.Q" in stmts[1]
    assert "NOT (#I_StationToolOn_1)" in stmts[1]
    assert "#Timer_StationCoolingFan.Q" in stmts[1]
    assert "#Man_Mode" in stmts[1] and "#Emm_Mode" in stmts[1]
    # ③ ToolAtPos 线圈由 SR.Q 驱动(简单线圈 IF/ELSE 重构保留)
    assert "#ToolAtPos" in stmts[2] and "#SR_StationTool.Q" in stmts[2]
    # ④ 第二 TON:IN := SR.Q
    assert "#Timer_StationCoolingFan.TON(IN:=#SR_StationTool.Q" in stmts[3].replace(" ", "")


def test_fb1040_net7_no_statement_loss() -> None:
    """报告 §3.2:fold 23 条 → translate 必须零丢失、不错位。

    修复前净丢 4 条(EdgeDetc.JUMP 置位、ProgStart、BitStuckErr_HighCurrent、
    MainStep.S6 自锁——步进链断裂)。
    """
    block = _parse_fragment(FB1040_NET7)
    network = block.networks[0]
    network.folded = fold_network(network)
    folded_count = len(network.folded.statements)
    stmts = NetworkTranslator(block, network).translate()
    assert folded_count == 23
    assert len(stmts) == 23  # 零丢失
    joined = "\n".join(stmts)
    assert "TODO" not in joined  # O 门噪声清零(S8)
    assert joined.count(".TON(IN :=") == 3  # 三个 CoilTON 都发出定时器调用
    assert "#EdgeDetc.JUMP := TRUE" in joined
    assert '"DB1080_Component".Robot.Cmd.Auto.ProgStart := TRUE' in joined
    assert '"DB1148_PromptBeeper".Public.BitStuckErr_HighCurrent := TRUE' in joined
    # 步进链自锁保持:末条 S6 := (S2 AND HomePos) OR (S2 AND S6)
    last = stmts[-1]
    assert "#MainStep.S6 :=" in last and "#MainStep.S6" in last.split(":=", 1)[1]
    assert "#MainStep.S2" in last


def test_fc2300_net5_math_restored() -> None:
    """报告 §3.1 FC2300 网络 5:修复前整网只剩两条 TODO 注释,计算逻辑全丢。"""
    stmts = _translate(FC2300_NET5)
    assert len(stmts) == 2
    assert "TODO" not in "\n".join(stmts)
    assert "#High" in stmts[0] and "* 64" in stmts[0]
    assert "#Temp_PLC_Minute:=" in stmts[0].replace(" ", "")
    assert "+ (" in stmts[1] and "SECOND" in stmts[1]


# ---------------------------------------------------------------------------
# S2 — 伪环守卫清零(消费路径 + 自身机器)
# ---------------------------------------------------------------------------


def test_fb5002_net1_no_loop_guard_and_polarity_kept() -> None:
    """报告 §3.1 FB5002 网络 1:共享支路复用,自锁完整,取反极性保留。"""
    stmts = _translate(FB5002_NET1)
    joined = "\n".join(stmts)
    assert "loop guard" not in joined
    assert "TODO" not in joined
    # 取反触点极性(解析层 Negated)透传到翻译层
    assert "NOT (#EMMode)" in joined and "NOT (#i_AutoRunning)" in joined
    # 启保停:DT2 := (start AND PS10) OR (start AND DT2) AND DT1
    dt2 = next(s for s in stmts if "#Aux.DT2 :=" in s)
    assert "PLS.PS10" in dt2 and "#Aux.DT2" in dt2.split(":=", 1)[1]
    dt1 = next(s for s in stmts if "#Aux.DT1 :=" in s)
    assert "PLS.PS10" in dt1 and "#Aux.DT1" in dt1.split(":=", 1)[1]


def test_fb5002_net1_own_machine_shared_branch_reuse() -> None:
    """S2(字符串版):folded 未挂载时,scl.py 自身机器同样不得输出环守卫。

    修复前:Wire 把 Contact38.out 扇出到 5 个下游,第二支路评估同一链时被
    ``_visited`` 判"环" → ``((* loop guard *) AND …)`` 嵌入表达式。
    """
    stmts = _translate(FB5002_NET1, fold=False)
    joined = "\n".join(stmts)
    assert "loop guard" not in joined
    dt2 = next(s for s in stmts if "#Aux.DT2 :=" in s)
    assert "PLS.PS10" in dt2 and "#Aux.DT2" in dt2.split(":=", 1)[1]


# ---------------------------------------------------------------------------
# S5/S6/S7(字符串版)— 自身表达式机器与折叠线约定一致
# ---------------------------------------------------------------------------


def test_fb2009_net1_own_machine_box_q_and_coil_drivers() -> None:
    """S5(字符串版):箱体 Q / 线圈直通作为 RLO 驱动 + CoilTON 自发射。"""
    stmts = _translate(FB2009_NET1, fold=False)
    joined = "\n".join(stmts)
    assert len(stmts) == 4
    # CoilTON → 定时器调用(自身发射分支)
    assert (
        "#Timer_StationToolOn.TON(IN := (#Auto_Mode AND #I_StationToolOn_1) "
        "AND #I_StationToolOn_2, PT := T#2s);" in joined
    )
    # SR box:operand 引脚实例 + 小写 s/r1 引脚
    sr = next(s for s in stmts if ".SR(" in s)
    assert "#SR_StationTool.SR(" in sr
    assert "S := #Timer_StationToolOn.Q" in sr
    assert "NOT (#I_StationToolOn_1)" in sr and "#Timer_StationCoolingFan.Q" in sr
    # SR.q → Coil46 / CoilTON47(S5 箱体输出驱动)
    tool = next(s for s in stmts if "#ToolAtPos" in s)
    assert "#SR_StationTool.Q" in tool
    assert "#Timer_StationCoolingFan.TON(IN := #SR_StationTool.Q, PT := #CoolingTime);" in joined


def test_fb1060_net1_ton_q_gating_pre_rlo_and_no_todo_noise() -> None:
    """报告 §3.1 FB1060 网络 1:S5 TON.Q 门控 + S6 .pre 前置 + S8 噪声清零。"""
    stmts = _translate(FB1060_NET1)
    joined = "\n".join(stmts)
    # S8:O 门 / PBox 沿触点已折进下游,不再发 TODO 噪声
    assert "TODO[O]" not in joined and "TODO[PBox]" not in joined and "TODO[Not]" not in joined
    assert "loop guard" not in joined
    # S5:SCoil 由 TON.Q 门控(修复前上电常置位)
    assert (
        'IF "Timer_RecvEmmMode".Q THEN "DB1900_Communication_PC".Send.PowerOff := TRUE; END_IF;'
        in joined
    )
    # S6:Eq93 的 .pre(ClearHoleNoReq)前置到比较器
    clear = next(s for s in stmts if "ClearHoleNum" in s)
    assert "ClearHoleNoReq" in clear and "(#Aux.HoleNo = 0)" in clear


def test_fb1060_net1_own_machine_comparator_pre_rlo() -> None:
    """S6(字符串版):.pre → ``(<pre> AND (a OP b))``。"""
    stmts = _translate(FB1060_NET1, fold=False)
    clear = next(s for s in stmts if "ClearHoleNum" in s)
    assert '"DB1900_Communication_PC".Recv.ClearHoleNoReq AND (#Aux.HoleNo = 0)' in clear
    power = next(s for s in stmts if "Send.PowerOff" in s and "TRUE" in s)
    assert '"Timer_RecvEmmMode".Q' in power


def test_fb5009_net2_convert_en_gated() -> None:
    """S7:Convert 框 EN → IF 门控(消费路径与自身机器都要)。"""
    for fold in (True, False):
        stmts = _translate(FB5009_NET2, fold=fold)
        joined = "\n".join(stmts)
        assert "#Cmd.Read1" in joined and "#Cmd.Read2" in joined
        gated1 = next(s for s in stmts if "TP_ActualAI_1" in s)
        assert gated1.startswith("IF ") and "#Cmd.Read1" in gated1 and ":= #IW" in gated1
        gated2 = next(s for s in stmts if "TP_ActualAI_2" in s)
        assert gated2.startswith("IF ") and "#Cmd.Read2" in gated2


def test_fc2300_net5_own_machine_math_assignment() -> None:
    """S1(字符串版):数学框自身发射分支 → 赋值表达式(EN 门控)。"""
    stmts = _translate(FC2300_NET5, fold=False)
    assert len(stmts) == 2
    assert "IF #High THEN #Temp_PLC_Minute :=" in stmts[0]
    assert "* 64" in stmts[0]
    assert "#Temp_PLC_Minute+(" in stmts[1].replace(" ", "")


# ---------------------------------------------------------------------------
# 消费契约 — kind 不符不静默丢弃;无主语句也要发出
# ---------------------------------------------------------------------------


def test_folded_kind_mismatch_traced_never_dropped() -> None:
    """kind 不符:显式 TODO 留痕 + 折叠语句仍然发出(禁止静默丢弃)。"""
    block = _parse_fragment(FB2009_NET1)
    network = block.networks[0]
    network.folded = FoldedNetwork(
        network_id=network.id,
        statements=[AssignStmt(None, Lit(True), kind="move", target_scl="Weird := 1;")],
    )
    stmts = NetworkTranslator(block, network).translate()
    joined = "\n".join(stmts)
    assert "TODO[translate-align]" in joined
    assert "Weird := 1;" in joined
    # 其余部件回退到自身发射,网络逻辑仍然完整
    assert "#SR_StationTool.SR(" in joined
    assert "#Timer_StationCoolingFan.TON(IN:=#SR_StationTool.Q" in joined.replace(" ", "")


def test_folded_orphan_statement_still_emitted() -> None:
    """fold 产出的无主语句(part 不在本网络)不允许无声蒸发。"""
    block = _parse_fragment(FC2300_NET5)
    network = block.networks[0]
    network.folded = FoldedNetwork(
        network_id=network.id,
        statements=[
            FoldStmt(None, Lit(True), kind="call", target_scl="Orphan();", part_uuid="999"),
        ],
    )
    stmts = NetworkTranslator(block, network).translate()
    joined = "\n".join(stmts)
    assert "Orphan();" in joined
    # 数学框自身发射不受影响
    assert "* 64" in joined
