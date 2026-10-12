"""Generate compact SimaticML fixtures for instruction coverage tests.

Run: python tests/fixtures/tia_parts/_gen.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _doc(inner: str, doc_type: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <Engineering version="V17" />\n'
        f"{inner}"
        f"  <DocumentType>{doc_type}</DocumentType>\n"
        "</Document>\n"
    )


def _iface(members: str) -> str:
    return f"""      <SW.Blocks.InterfaceSection ID="3" CompositionName="Interface">
        <Sections>
{members}
          <Section Name="InOut" />
          <Section Name="Temp" />
          <Section Name="Constant" />
        </Sections>
      </SW.Blocks.InterfaceSection>
"""


def _net(nid: str, title: str, flg: str, lang: str = "LAD") -> str:
    return f"""      <SW.Blocks.CompileUnit ID="{nid}" CompositionName="Networks">
        <AttributeList>
          <ProgrammingLanguage>{lang}</ProgrammingLanguage>
        </AttributeList>
        <ObjectList>
          <MultilingualText ID="{nid}t" CompositionName="Title">
            <ObjectList>
              <MultilingualTextItem ID="{nid}ti" CompositionName="Items">
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>{title}</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
          {flg}
        </ObjectList>
      </SW.Blocks.CompileUnit>
"""


def _block(
    name: str,
    number: int,
    btype: str,
    lang: str,
    iface: str,
    networks: str,
    extra_attrs: str = "",
    comment: str = "",
    source_text: str = "",
) -> str:
    comment_xml = ""
    if comment:
        comment_xml = f"""      <MultilingualText ID="1" CompositionName="Comment">
        <ObjectList>
          <MultilingualTextItem ID="2" CompositionName="Items">
            <AttributeList>
              <Culture>en-US</Culture>
              <Text>{comment}</Text>
            </AttributeList>
          </MultilingualTextItem>
        </ObjectList>
      </MultilingualText>
"""
    src = f"      <SourceText>{source_text}</SourceText>\n" if source_text else ""
    inner = f"""  <SW.Blocks.ObjectSW ID="0" CompositionName="Blocks">
    <AttributeList>
      <Name>{name}</Name>
      <Number>{number}</Number>
      <ProgrammingLanguage>{lang}</ProgrammingLanguage>
{extra_attrs}    </AttributeList>
    <ObjectList>
{comment_xml}{iface}{src}{networks}    </ObjectList>
  </SW.Blocks.ObjectSW>
"""
    suffix = {"OB": "OB", "FB": "FB", "FC": "FC", "DB": "DB"}.get(btype, "FB")
    return _doc(inner, f"Simatic.ML.{suffix}")


def _acc(uid: str, name: str) -> str:
    return f'              <Access Scope="LocalVariable" UId="{uid}">\n                <Symbol><Component Name="{name}" /></Symbol>\n              </Access>'


def _lit(uid: str, value: str, typ: str = "Time") -> str:
    return (
        f'              <Access Scope="LiteralConstant" UId="{uid}">\n'
        f"                <Constant><ConstantType>{typ}</ConstantType>"
        f"<ConstantValue>{value}</ConstantValue></Constant>\n"
        "              </Access>"
    )


def _wire(uid: str, body: str) -> str:
    return f'              <Wire UId="{uid}">\n                {body}\n              </Wire>'


def write(name: str, xml: str) -> None:
    path = ROOT / name
    path.write_text(xml, encoding="utf-8")
    print(path.name)


def main() -> None:
    # Contact / NegContact / Coil / Set / Reset
    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "Start")}
{_acc("22", "Stop")}
{_acc("23", "Run")}
{_acc("24", "Latched")}
{_acc("25", "Latched")}
              <Part Name="Contact" UId="31" />
              <Part Name="NegContact" UId="32" />
              <Part Name="Coil" UId="33" />
              <Part Name="SetCoil" UId="34" />
              <Part Name="Reset" UId="35" />
            </Parts>
            <Wires>
{_wire("41", '<Powerrail /><NameCon UId="31" Name="in" />')}
{_wire("42", '<IdentCon UId="21" /><NameCon UId="31" Name="operand" />')}
{_wire("43", '<NameCon UId="31" Name="out" /><NameCon UId="32" Name="in" />')}
{_wire("44", '<IdentCon UId="22" /><NameCon UId="32" Name="operand" />')}
{_wire("45", '<NameCon UId="32" Name="out" /><NameCon UId="33" Name="in" /><NameCon UId="35" Name="in" />')}
{_wire("46", '<IdentCon UId="23" /><NameCon UId="33" Name="operand" />')}
{_wire("47", '<Powerrail /><NameCon UId="34" Name="in" />')}
{_wire("48", '<IdentCon UId="24" /><NameCon UId="34" Name="operand" />')}
{_wire("49", '<IdentCon UId="25" /><NameCon UId="35" Name="operand" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Contacts.xml",
        _block(
            "FC_Contacts",
            10,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Start" Datatype="Bool" />\n'
                '            <Member Name="Stop" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Run" Datatype="Bool" />\n'
                '            <Member Name="Latched" Datatype="Bool" />\n'
                "          </Section>"
            ),
            _net("10", "contacts set reset", flg),
        ),
    )

    # SR / RS
    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "SetIn")}
{_acc("22", "RstIn")}
{_acc("23", "Q1")}
{_acc("24", "SetIn")}
{_acc("25", "RstIn")}
{_acc("26", "Q2")}
              <Part Name="SR" UId="31">
                <Instance Scope="LocalVariable"><Component Name="SR1" /></Instance>
              </Part>
              <Part Name="RS" UId="32">
                <Instance Scope="LocalVariable"><Component Name="RS1" /></Instance>
              </Part>
            </Parts>
            <Wires>
{_wire("41", '<Powerrail /><NameCon UId="31" Name="S" /><NameCon UId="32" Name="R1" />')}
{_wire("42", '<IdentCon UId="21" /><NameCon UId="31" Name="S1" />')}
{_wire("43", '<IdentCon UId="22" /><NameCon UId="31" Name="R" />')}
{_wire("44", '<NameCon UId="31" Name="Q" /><IdentCon UId="23" />')}
{_wire("45", '<IdentCon UId="24" /><NameCon UId="32" Name="S" />')}
{_wire("46", '<IdentCon UId="25" /><NameCon UId="32" Name="R1" />')}
{_wire("47", '<NameCon UId="32" Name="Q" /><IdentCon UId="26" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Latch.xml",
        _block(
            "FC_Latch",
            11,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="SetIn" Datatype="Bool" />\n'
                '            <Member Name="RstIn" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Q1" Datatype="Bool" />\n'
                '            <Member Name="Q2" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Static">\n'
                '            <Member Name="SR1" Datatype="SR" />\n'
                '            <Member Name="RS1" Datatype="RS" />\n'
                "          </Section>"
            ),
            _net("10", "sr rs boxes", flg),
        ),
    )

    def _timer_net(part_name: str, inst: str, uid_base: int) -> str:
        p, a, b, c, d = uid_base, uid_base + 1, uid_base + 2, uid_base + 3, uid_base + 4
        return f"""<FlgNet ID="n{part_name}">
            <Parts>
{_acc(str(a), "Enable")}
{_lit(str(b), "T#1S")}
{_acc(str(c), "Done")}
              <Part Name="{part_name}" UId="{p}">
                <Instance Scope="LocalVariable"><Component Name="{inst}" /></Instance>
              </Part>
            </Parts>
            <Wires>
{_wire(str(d), f'<Powerrail /><NameCon UId="{p}" Name="IN" />')}
{_wire(str(d + 1), f'<IdentCon UId="{a}" /><NameCon UId="{p}" Name="IN" />')}
{_wire(str(d + 2), f'<IdentCon UId="{b}" /><NameCon UId="{p}" Name="PT" />')}
{_wire(str(d + 3), f'<NameCon UId="{p}" Name="Q" /><IdentCon UId="{c}" />')}
            </Wires>
          </FlgNet>"""

    nets = "".join(
        _net(str(10 + i), title, _timer_net(pname, inst, 30 + i * 10))
        for i, (title, pname, inst) in enumerate(
            [
                ("ton", "TON", "TOn"),
                ("tof", "TOF", "TOff"),
                ("tp", "TP", "TPulse"),
                ("tonr", "TONR", "TOnR"),
            ]
        )
    )
    write(
        "FC_Timers.xml",
        _block(
            "FC_Timers",
            12,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Enable" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Done" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Static">\n'
                '            <Member Name="TOn" Datatype="TON" />\n'
                '            <Member Name="TOff" Datatype="TOF" />\n'
                '            <Member Name="TPulse" Datatype="TP" />\n'
                '            <Member Name="TOnR" Datatype="TONR" />\n'
                "          </Section>"
            ),
            nets,
        ),
    )

    def _ctr_net(part_name: str, inst: str, pin: str, uid_base: int) -> str:
        p, a, b, c, d = uid_base, uid_base + 1, uid_base + 2, uid_base + 3, uid_base + 4
        return f"""<FlgNet ID="n{part_name}">
            <Parts>
{_acc(str(a), "Pulse")}
{_lit(str(b), "10", "Int")}
{_acc(str(c), "Count")}
              <Part Name="{part_name}" UId="{p}">
                <Instance Scope="LocalVariable"><Component Name="{inst}" /></Instance>
              </Part>
            </Parts>
            <Wires>
{_wire(str(d), f'<IdentCon UId="{a}" /><NameCon UId="{p}" Name="{pin}" />')}
{_wire(str(d + 1), f'<IdentCon UId="{b}" /><NameCon UId="{p}" Name="PV" />')}
{_wire(str(d + 2), f'<NameCon UId="{p}" Name="CV" /><IdentCon UId="{c}" />')}
            </Wires>
          </FlgNet>"""

    nets = "".join(
        _net(str(10 + i), title, _ctr_net(pname, inst, pin, 30 + i * 10))
        for i, (title, pname, inst, pin) in enumerate(
            [
                ("ctu", "CtU", "CUp", "CU"),
                ("ctd", "CtD", "CDn", "CD"),
                ("ctud", "CtUD", "CUd", "CU"),
            ]
        )
    )
    write(
        "FC_Counters.xml",
        _block(
            "FC_Counters",
            13,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Pulse" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Count" Datatype="Int" />\n'
                "          </Section>\n"
                '          <Section Name="Static">\n'
                '            <Member Name="CUp" Datatype="CTU" />\n'
                '            <Member Name="CDn" Datatype="CTD" />\n'
                '            <Member Name="CUd" Datatype="CTUD" />\n'
                "          </Section>"
            ),
            nets,
        ),
    )

    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "Src")}
{_acc("22", "Dst")}
{_acc("23", "Src")}
{_acc("24", "ConvOut")}
{_acc("25", "Src")}
{_acc("26", "RndOut")}
{_acc("27", "K")}
{_acc("28", "Src")}
{_acc("29", "MuxOut")}
{_acc("20", "Src")}
{_acc("19", "DemuxOut")}
{_acc("18", "K")}
              <Part Name="Move" UId="31" />
              <Part Name="Convert" UId="32">
                <TemplateValue Name="Type" Type="Type">Int</TemplateValue>
              </Part>
              <Part Name="Round" UId="33" />
              <Part Name="Mux" UId="34" />
              <Part Name="Demux" UId="35" />
            </Parts>
            <Wires>
{_wire("41", '<IdentCon UId="21" /><NameCon UId="31" Name="in" />')}
{_wire("42", '<NameCon UId="31" Name="out1" /><IdentCon UId="22" />')}
{_wire("43", '<IdentCon UId="23" /><NameCon UId="32" Name="in" />')}
{_wire("44", '<NameCon UId="32" Name="out" /><IdentCon UId="24" />')}
{_wire("45", '<IdentCon UId="25" /><NameCon UId="33" Name="in" />')}
{_wire("46", '<NameCon UId="33" Name="out" /><IdentCon UId="26" />')}
{_wire("47", '<IdentCon UId="27" /><NameCon UId="34" Name="k" />')}
{_wire("48", '<IdentCon UId="28" /><NameCon UId="34" Name="in0" />')}
{_wire("49", '<NameCon UId="34" Name="out" /><IdentCon UId="29" />')}
{_wire("50", '<IdentCon UId="18" /><NameCon UId="35" Name="k" />')}
{_wire("51", '<IdentCon UId="20" /><NameCon UId="35" Name="in" />')}
{_wire("52", '<NameCon UId="35" Name="out" /><IdentCon UId="19" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Move.xml",
        _block(
            "FC_Move",
            14,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Src" Datatype="Real" />\n'
                '            <Member Name="K" Datatype="Int" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Dst" Datatype="Real" />\n'
                '            <Member Name="ConvOut" Datatype="Int" />\n'
                '            <Member Name="RndOut" Datatype="Int" />\n'
                '            <Member Name="MuxOut" Datatype="Real" />\n'
                '            <Member Name="DemuxOut" Datatype="Real" />\n'
                "          </Section>"
            ),
            _net("10", "move convert mux", flg),
        ),
    )

    ops = ["Eq", "Ne", "Gt", "Ge", "Lt", "Le"]
    parts = "\n".join(
        [
            _acc("21", "A"),
            _acc("22", "B"),
            _acc("23", "Ok"),
            *[f'              <Part Name="{op}" UId="{31 + i}" />' for i, op in enumerate(ops)],
            '              <Part Name="Coil" UId="40" />',
        ]
    )
    wires = "\n".join(
        [
            _wire("41", '<Powerrail /><NameCon UId="31" Name="pre" />'),
            _wire("42", '<IdentCon UId="21" /><NameCon UId="31" Name="in1" />'),
            _wire("43", '<IdentCon UId="22" /><NameCon UId="31" Name="in2" />'),
            *[
                _wire(
                    str(44 + i),
                    f'<NameCon UId="{31 + i}" Name="out" /><NameCon UId="{32 + i}" Name="in1" />',
                )
                for i in range(5)
            ],
            _wire("50", '<IdentCon UId="21" /><NameCon UId="32" Name="in1" /><NameCon UId="33" Name="in1" /><NameCon UId="34" Name="in1" /><NameCon UId="35" Name="in1" /><NameCon UId="36" Name="in1" />'),
            _wire("51", '<IdentCon UId="22" /><NameCon UId="32" Name="in2" /><NameCon UId="33" Name="in2" /><NameCon UId="34" Name="in2" /><NameCon UId="35" Name="in2" /><NameCon UId="36" Name="in2" />'),
            _wire("52", '<NameCon UId="36" Name="out" /><NameCon UId="40" Name="in" />'),
            _wire("53", '<IdentCon UId="23" /><NameCon UId="40" Name="operand" />'),
        ]
    )
    flg = f"""<FlgNet ID="13">
            <Parts>
{parts}
            </Parts>
            <Wires>
{wires}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Compare.xml",
        _block(
            "FC_Compare",
            15,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="A" Datatype="Int" />\n'
                '            <Member Name="B" Datatype="Int" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Ok" Datatype="Bool" />\n'
                "          </Section>"
            ),
            _net("10", "compare chain", flg),
        ),
    )

    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "Go")}
              <Part Name="Label" UId="31">
                <TemplateValue Name="Name" Type="String">SKIP</TemplateValue>
              </Part>
              <Part Name="Jump" UId="32">
                <TemplateValue Name="Label" Type="String">SKIP</TemplateValue>
              </Part>
              <Part Name="Contact" UId="33" />
              <Part Name="Return" UId="34" />
            </Parts>
            <Wires>
{_wire("41", '<Powerrail /><NameCon UId="32" Name="in" /><NameCon UId="33" Name="in" />')}
{_wire("42", '<IdentCon UId="21" /><NameCon UId="33" Name="operand" />')}
{_wire("43", '<NameCon UId="33" Name="out" /><NameCon UId="34" Name="in" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Jump.xml",
        _block(
            "FC_Jump",
            16,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Go" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output" />'
            ),
            _net("10", "jump label return", flg),
        ),
    )

    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("23", "EnoFlag")}
              <Part Name="Call" UId="21">
                <Access Scope="LocalVariable" UId="22" Name="instance">
                  <Symbol><Component Name="MotorInst" /></Symbol>
                </Access>
                <TemplateValue Name="Call" Type="String">FB_Motor</TemplateValue>
              </Part>
            </Parts>
            <Wires>
{_wire("31", '<Powerrail /><NameCon UId="21" Name="in" />')}
{_wire("32", '<NameCon UId="21" Name="ENO" /><IdentCon UId="23" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_CallEno.xml",
        _block(
            "FC_CallEno",
            17,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input" />\n'
                '          <Section Name="Output">\n'
                '            <Member Name="EnoFlag" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Static">\n'
                '            <Member Name="MotorInst" Datatype="FB_Motor" />\n'
                "          </Section>"
            ),
            _net("10", "call with eno", flg),
        ),
    )

    write(
        "FC_NativeScl.xml",
        _block(
            "FC_NativeScl",
            18,
            "FC",
            "SCL",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="In" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Out" Datatype="Bool" />\n'
                "          </Section>"
            ),
            "",
            source_text="#Out := #In;\n#Out := #Out OR #In;",
            comment="native SCL body passthrough",
        ),
    )

    stl = """          <StatementList>
            <StlStatement UId="1">
              <StlToken Text="A" />
              <Access Scope="LocalVariable"><Symbol><Component Name="Start" /></Symbol></Access>
            </StlStatement>
            <StlStatement UId="2">
              <StlToken Text="AN" />
              <Access Scope="LocalVariable"><Symbol><Component Name="Stop" /></Symbol></Access>
            </StlStatement>
            <StlStatement UId="3">
              <StlToken Text="=" />
              <Access Scope="LocalVariable"><Symbol><Component Name="Run" /></Symbol></Access>
            </StlStatement>
            <StlStatement UId="4">
              <StlToken Text="S" />
              <Access Scope="LocalVariable"><Symbol><Component Name="Latched" /></Symbol></Access>
            </StlStatement>
          </StatementList>"""
    write(
        "FC_Stl.xml",
        _block(
            "FC_Stl",
            19,
            "FC",
            "STL",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Start" Datatype="Bool" />\n'
                '            <Member Name="Stop" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Run" Datatype="Bool" />\n'
                '            <Member Name="Latched" Datatype="Bool" />\n'
                "          </Section>"
            ),
            _net("10", "stl rlo", stl, lang="STL"),
        ),
    )

    graph = """          <Step Name="Init" Number="1" UId="s1">
            <Action Text="#Ready := TRUE" />
          </Step>
          <Step Name="Run" Number="2" UId="s2">
            <Action Text="#Busy := TRUE" />
          </Step>
          <Transition Name="T1" From="Init" To="Run" Condition="#Start" UId="t1" />
"""
    write(
        "FB_Graph.xml",
        _block(
            "FB_Graph",
            20,
            "FB",
            "GRAPH",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="Start" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="Ready" Datatype="Bool" />\n'
                '            <Member Name="Busy" Datatype="Bool" />\n'
                "          </Section>"
            ),
            _net("10", "graph sequence", graph, lang="GRAPH"),
        ),
    )

    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "X")}
              <Part Name="MysteriousBox" UId="31" />
              <Part Name="Coil" UId="32" />
            </Parts>
            <Wires>
{_wire("41", '<Powerrail /><NameCon UId="31" Name="in" />')}
{_wire("42", '<IdentCon UId="21" /><NameCon UId="31" Name="operand" />')}
{_wire("43", '<NameCon UId="31" Name="out" /><NameCon UId="32" Name="in" />')}
{_wire("44", '<IdentCon UId="21" /><NameCon UId="32" Name="operand" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FC_Unknown.xml",
        _block(
            "FC_Unknown",
            21,
            "FC",
            "LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="X" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output" />'
            ),
            _net("10", "unknown part", flg),
        ),
    )

    flg = f"""<FlgNet ID="13">
            <Parts>
{_acc("21", "EStopOk")}
{_acc("22", "SafeOut")}
              <Part Name="Contact" UId="31" />
              <Part Name="Coil" UId="32" />
            </Parts>
            <Wires>
{_wire("41", '<Powerrail /><NameCon UId="31" Name="in" />')}
{_wire("42", '<IdentCon UId="21" /><NameCon UId="31" Name="operand" />')}
{_wire("43", '<NameCon UId="31" Name="out" /><NameCon UId="32" Name="in" />')}
{_wire("44", '<IdentCon UId="22" /><NameCon UId="32" Name="operand" />')}
            </Wires>
          </FlgNet>"""
    write(
        "FB_FSafety.xml",
        _block(
            "F-FB_EStop",
            123,
            "FB",
            "F-LAD",
            _iface(
                '          <Section Name="Input">\n'
                '            <Member Name="EStopOk" Datatype="Bool" />\n'
                "          </Section>\n"
                '          <Section Name="Output">\n'
                '            <Member Name="SafeOut" Datatype="Bool" />\n'
                "          </Section>"
            ),
            _net("10", "failsafe coil", flg, lang="F-LAD"),
            extra_attrs="      <IsFailsafe>true</IsFailsafe>\n",
            comment="failsafe emergency stop",
        ),
    )

    hw = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V17" />
  <HW.Devices.Device Name="PLC_1" TypeIdentifier="OrderNumber:6ES7 515-2AM02-0AB0/V2.9">
    <Slot>0</Slot>
    <Address>192.168.0.1</Address>
    <Comment><Text>CPU 1515F</Text></Comment>
  </HW.Devices.Device>
</Document>
"""
    write("HW_Device.xml", hw)


if __name__ == "__main__":
    main()
