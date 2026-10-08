# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
.PHONY: test web check run package spdx bedrock-compat

test:
	python3 -m unittest discover -s tests -v

web:
	cd web && npm ci && npm run build

spdx:
	python3 scripts/check-spdx.py

check: spdx test
	cd web && npm run build && npm test

run:
	python3 -m nuvora.server --demo

package:
	python3 -m pip wheel --no-deps . -w dist

bedrock-compat:
	scripts/bedrock/run-compat.sh
