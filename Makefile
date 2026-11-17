PYTHON ?= /usr/bin/python3

.PHONY: test smoke dry-run

test:
	$(PYTHON) -m unittest -v

smoke:
	$(PYTHON) tools/run_smoke.py

dry-run:
	./install.sh --dry-run
