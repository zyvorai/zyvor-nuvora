.PHONY: test web check run package

test:
	python3 -m unittest discover -s tests -v

web:
	cd web && npm ci && npm run build

check: test
	cd web && npm run build && npm test

run:
	python3 -m nuvora.server --demo

package:
	python3 -m pip wheel --no-deps . -w dist
