import xml.etree.ElementTree as ET

tree = ET.parse(r'PLC_Openness_data\hr001\export\plc\CPU_1200\blocks\004_AutoStep_FB1060_AutoStep.xml')
members = tree.findall('.//{*}Section[@Name="Static"]/{*}Member')
print(f'Total static members: {len(members)}')
for i, m in enumerate(members, 1):
    print(f"{i:2d}. {m.attrib.get('Name')}: {m.attrib.get('Datatype')}")
