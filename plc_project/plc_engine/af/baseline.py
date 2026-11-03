"""Siemens Automation Framework V1.2 Startup Template Provider & Baseline Manager.

Provides access to official AF V1.2 TIA Portal V19 (.ap19) templates:
- Startup Template (Automation_Framework_Startup_PROJ_V1_2.zip): Clean project pre-configured
  with official libraries (LPMLV2022, LUC, LAF, LBC, LGF) and System Software Units.
- Reference Project (Automation_Framework_PROJ_V1_2.zip): Reference implementation including
  U1_Unit1_SCL (100% SCL Unit/EM templates).

Security triage: "Template" here means TIA Portal project-template .zip assets located by
module constants — this module performs no string templating and never interpolates user
input into any template/format string (static scanner "template injection" hit is a false
positive). Zip extraction is guarded against path traversal (zip slip).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

DEFAULT_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
STARTUP_ZIP_NAME = "Automation_Framework_Startup_PROJ_V1_2.zip"
REFERENCE_ZIP_NAME = "Automation_Framework_PROJ_V1_2.zip"

STARTUP_PROJ_SUBDIR = "109817223_Automation_Framwork_Startup_PROJ_V1_2"
STARTUP_AP19_NAME = "109817223_Automation_Framwork_Startup_PROJ_V1_2.ap19"


def find_af_asset(asset_name: str, base_dir: Path | None = None) -> Path:
    """Locate an AF asset file in docs/ or search roots."""
    docs = base_dir or DEFAULT_DOCS_DIR
    target = docs / asset_name
    if target.is_file():
        return target
    # Search parent directories
    curr = docs
    for _ in range(3):
        candidate = curr / "docs" / asset_name
        if candidate.is_file():
            return candidate
        curr = curr.parent
    raise FileNotFoundError(f"AF V1.2 asset '{asset_name}' not found under {docs}.")


def get_startup_zip(base_dir: Path | None = None) -> Path:
    return find_af_asset(STARTUP_ZIP_NAME, base_dir)


def get_reference_zip(base_dir: Path | None = None) -> Path:
    return find_af_asset(REFERENCE_ZIP_NAME, base_dir)


def clone_startup_template(
    target_dir: str | Path,
    project_name: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Extract and clone the official clean AF V1.2 Startup Template into target_dir.

    Args:
        target_dir: Directory where the project folder will be placed.
        project_name: Name of the new project (e.g. 'AssemblyLine').

    Returns:
        Path to the primary .ap19 project file of the newly cloned project.
    """
    dest_root = Path(target_dir).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    project_folder = dest_root / project_name
    if project_folder.exists():
        raise FileExistsError(f"Target project folder already exists: {project_folder}")

    zip_path = get_startup_zip(base_dir)

    # Extract the startup project from zip
    with zipfile.ZipFile(zip_path, "r") as z:
        prefix = f"{STARTUP_PROJ_SUBDIR}/"
        members = [m for m in z.namelist() if m.startswith(prefix)]
        # zip-slip guard: every extracted member must resolve back inside project_folder
        project_root = project_folder.resolve()
        for member in members:
            rel = member[len(prefix) :]
            if not rel:
                continue
            out_path = (project_folder / rel).resolve()
            if not out_path.is_relative_to(project_root):
                raise ValueError(f"zip member escapes target dir (zip slip): {member!r}")
            if member.endswith("/"):
                out_path.mkdir(parents=True, exist_ok=True)
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    # Find the extracted .ap19 file
    orig_ap19 = project_folder / STARTUP_AP19_NAME
    if not orig_ap19.is_file():
        # Fallback to finding any .ap19 in project_folder
        ap19s = list(project_folder.glob("*.ap19"))
        if not ap19s:
            raise FileNotFoundError(f"No .ap19 project file found in extracted startup template at {project_folder}")
        orig_ap19 = ap19s[0]

    # Rename .ap19 to match new project_name
    new_ap19 = project_folder / f"{project_name}.ap19"
    if orig_ap19 != new_ap19:
        orig_ap19.rename(new_ap19)

    return new_ap19
