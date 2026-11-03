import xml.etree.ElementTree as ET

tree = ET.parse(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml')
for m in tree.findall('.//{*}Section[@Name="Static"]/{*}Member'):
    mname = m.attrib.get('Name')
    mtype = m.attrib.get('Datatype')
    children = m.findall('./{*}Member')
    if children:
        print(f"{mname}: {mtype}")
        for c in children:
            print(f"    {c.attrib.get('Name')}: {c.attrib.get('Datatype')}")
    else:
        print(f"{mname}: {mtype}")
