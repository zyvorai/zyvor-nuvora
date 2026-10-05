# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Verify an exported audit chain offline. Detects tampering, not authenticity."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('file',type=Path)
args=parser.parse_args()
value=json.loads(args.file.read_text())
previous='0'*64
for record in value['events']:
    event={k:record[k] for k in ('actor','action','target','detail','time')}
    canonical=json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    digest=hashlib.sha256((previous+canonical).encode()).hexdigest()
    if record['previous']!=previous or record['digest']!=digest:
        print('FAILED at sequence',record['seq']);sys.exit(1)
    previous=digest
print('VERIFIED',len(value['events']),'events. Tip:',previous)
