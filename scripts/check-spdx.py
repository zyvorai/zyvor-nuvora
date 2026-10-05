#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Check (or with --fix, add) the SPDX license header on every source file."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TAG='SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0'
DIRS=['nuvora','web/src','scripts','sdk','tests']
COMMENT={'.py':'# ','.sh':'# ','.ts':'// ','.tsx':'// ','.cjs':'// '}
SKIP={'node_modules','static','__pycache__'}


def files():
    for d in DIRS:
        for path in sorted((ROOT/d).rglob('*')):
            if path.suffix in COMMENT and path.is_file() and not SKIP.intersection(path.relative_to(ROOT).parts):
                yield path


def main():
    fix='--fix' in sys.argv
    missing=[]
    for path in files():
        text=path.read_text()
        if any(TAG in line for line in text.split('\n')[:3]):
            continue
        if not fix:
            missing.append(path.relative_to(ROOT))
            continue
        header=COMMENT[path.suffix]+TAG+'\n'
        if text.startswith('#!'):
            first,_,rest=text.partition('\n')
            path.write_text(first+'\n'+header+rest)
        else:
            path.write_text(header+text)
    if missing:
        print('missing SPDX header (run scripts/check-spdx.py --fix):')
        for m in missing:
            print('  '+str(m))
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
