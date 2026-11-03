import xml.etree.ElementTree as ET

tree = ET.parse(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml')
sections = tree.findall('.//{*}Interface/{*}Sections/{*}Section')
for s in sections:
    sec_name = s.attrib.get('Name')
    print(f"=== Section {sec_name} ===")
    for m in s.findall('./{*}Member'):
        mname = m.attrib.get('Name')
        mtype = m.attrib.get('Datatype')
        print(f"  {mname}: {mtype}")
