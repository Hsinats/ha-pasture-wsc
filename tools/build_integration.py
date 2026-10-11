"""Create a zip containing exactly the installable custom component."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import subprocess
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,str(ROOT/"tools/sync_engine.py"),"--check"],check=True)
version = json.loads((ROOT/"custom_components/pasture_wsc/manifest.json").read_text(encoding="utf-8"))["version"]
target = ROOT/f"dist/pasture_wsc-{version}.zip"
target.parent.mkdir(exist_ok=True)
with ZipFile(target,"w",ZIP_DEFLATED) as archive:
    for path in sorted((ROOT/"custom_components/pasture_wsc").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path,path.relative_to(ROOT))
print(target)
