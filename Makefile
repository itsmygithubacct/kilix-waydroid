PYTHON ?= python3
INSTALL ?= install
PREFIX ?= /usr/local
DESTDIR ?=

.DEFAULT_GOAL := check

check: test
	$(PYTHON) -m compileall -q src tests kilix-waydroid

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

install:
	$(INSTALL) -d $(DESTDIR)$(PREFIX)/bin
	$(INSTALL) -m 0755 kilix-waydroid $(DESTDIR)$(PREFIX)/bin/kilix-waydroid
	$(INSTALL) -d $(DESTDIR)$(PREFIX)/lib/kilix-waydroid/kilix_waydroid
	$(INSTALL) -m 0644 src/kilix_waydroid/*.py \
		$(DESTDIR)$(PREFIX)/lib/kilix-waydroid/kilix_waydroid/

.PHONY: check install test
