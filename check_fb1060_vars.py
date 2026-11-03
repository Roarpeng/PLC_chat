import re

txt = open(r'PLC_Openness_data\hr001\pure_scl_fbs\FB1060_AutoStep.scl', 'r', encoding='utf-8').read()
header = txt[:txt.find('BEGIN')]
body = txt[txt.find('BEGIN'):]

vars_decl = re.findall(r'^\s*([A-Za-z0-9_"]+)\s*:\s*([A-Za-z0-9_"\[\]\.]+)', header, re.MULTILINE)
used_extra = []
for vname, vtype in vars_decl:
    clean = vname.strip('"')
    if clean in ['Status', 'Aux', 'EdgeDetc', 'MainStep', 'CycleTime', 'RobotAutoStep', 'HorDrillAutoStep', 'DownDrillAutoStep', 'DiamondAutoStep', 'StepStart']:
        continue
    refs = re.findall(r'#' + re.escape(clean) + r'\b', body)
    if refs:
        used_extra.append((clean, len(refs)))

print("Used extra variables:", used_extra)
