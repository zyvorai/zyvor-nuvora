# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Build a repository source ZIP with deterministic file inclusion and checksums."""
import hashlib
import json
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
output=root.parent/'zyvor-nuvora-0.2.0.zip'
excluded={'.git','node_modules','__pycache__','build','dist','.venv','.docusaurus','.cursor','screenshots'}
files=[]
for path in sorted(root.rglob('*')):
    relative=path.relative_to(root)
    if path.is_symlink() or not path.is_file() or any(p in excluded or p.endswith('.egg-info') for p in relative.parts):continue
    if path.suffix in ('.pyc','.tsbuildinfo') or '.db' in path.name:continue
    files.append(path)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.name!='MANIFEST.json'}
(root/'MANIFEST.json').write_text(json.dumps({'algorithm':'sha256','files':manifest},indent=2)+'\n')
files=[p for p in files if p.name!='MANIFEST.json']+[root/'MANIFEST.json']
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in files:archive.write(path,root.name+'/'+str(path.relative_to(root)))
print(json.dumps({'path':str(output),'files':len(files),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
