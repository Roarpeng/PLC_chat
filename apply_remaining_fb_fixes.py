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

# Fix FB1060: EdgeDetc.Pulse -> EdgeDetc.Pulse[0]
def fix_fb1060(txt):
    # Match #EdgeDetc.Pulse not followed by [
    txt = re.sub(r'#EdgeDetc\.Pulse(?!\[)', '#EdgeDetc.Pulse[0]', txt)
    return txt
update_file('FB1060_AutoStep.scl', fix_fb1060)

# Fix FB1061: EdgeDetc.Pulse -> EdgeDetc.Pulse[0]
def fix_fb1061(txt):
    txt = re.sub(r'#EdgeDetc\.Pulse(?!\[)', '#EdgeDetc.Pulse[0]', txt)
    return txt
update_file('FB1061_RobotAutoStep.scl', fix_fb1061)

# Fix FB1064: EdgeDetc.Pulse -> EdgeDetc.Pulse[0]
def fix_fb1064(txt):
    txt = re.sub(r'#EdgeDetc\.Pulse(?!\[)', '#EdgeDetc.Pulse[0]', txt)
    return txt
update_file('FB1064_DiamondAutostep.scl', fix_fb1064)

# Fix FB720: EdgeDetc.Pulse -> EdgeDetc.Pulse[0]
def fix_fb720(txt):
    txt = re.sub(r'#EdgeDetc\.Pulse(?!\[)', '#EdgeDetc.Pulse[0]', txt)
    return txt
update_file('FB720_KuKa_MainCtrl.scl', fix_fb720)

# Fix FB1040: EdgeDetc.JUMP -> EdgeDetc.JUMP[0]
def fix_fb1040(txt):
    txt = re.sub(r'#EdgeDetc\.JUMP(?!\[)', '#EdgeDetc.JUMP[0]', txt)
    return txt
update_file('FB1040_HomePos.scl', fix_fb1040)

# Fix FB2009: TON timer call and remove conflicting dummy variables
def fix_fb2009(txt):
    # Remove dummy variables PT, ET, IN, Q
    txt = re.sub(r'^\s*(?:PT|ET)\s*:\s*Time\s*;\s*//[^\r\n]*\r?\n?', '', txt, flags=re.MULTILINE)
    txt = re.sub(r'^\s*(?:IN|Q)\s*:\s*Bool\s*;\s*//[^\r\n]*\r?\n?', '', txt, flags=re.MULTILINE)
    
    # Ensure .TON calls
    txt = re.sub(r'#Timer_StationToolOn\s*\(\s*IN\s*:=', '#Timer_StationToolOn.TON(IN :=', txt)
    txt = re.sub(r'#Timer_StationCoolingFan\s*\(\s*IN\s*:=', '#Timer_StationCoolingFan.TON(IN :=', txt)
    return txt
update_file('FB2009_CoolingFanFunction.scl', fix_fb2009)

print("Batch fixes applied successfully.")
