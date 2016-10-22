#
# Copyright (C) 2016 Chris Cummins.
#
# This file is part of labm8.
#
# Labm8 is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# Labm8 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License
# along with labm8.  If not, see <http://www.gnu.org/licenses/>.
#
# path to virtualenv
VIRTUALENV := virtualenv
# path to python3
PYTHON3 := python3
PIP3 := pip3
# path to python2
PYTHON2 := python2
PIP2 := pip

# source virtualenvs
env3 := source env3/bin/activate &&
env2 := source env2/bin/activate &&

# create virtualenvs and install dependencies
virtualenv: env3/bin/activate env2/bin/activate

env3/bin/activate:
	$(VIRTUALENV) -p $(PYTHON3) env3
	$(env3)pip install -r requirements.txt
	$(env3)python ./setup.py install

env2/bin/activate:
	$(VIRTUALENV) -p $(PYTHON2) env2
	$(env2)pip install -r requirements.txt
	$(env2)python ./setup.py install

# run tests
.PHONY: test
test: virtualenv
	$(env3)python ./setup.py test
	$(env2)python ./setup.py test

# clean virtualenvs
.PHONY: clean
clean:
	rm -fr env3 env2

# install globally
.PHONY: install install3 install2
install3:
	$(PIP3) install -r requirements.txt
	$(PYTHON3) ./setup.py install

install2:
	$(PIP2) install -r requirements.txt
	$(PYTHON2) ./setup.py install

install: install3 install2

# generate documentation
.PHONY: docs
docs: install
	@for module in $$(cd labm8; ls *.py | grep -v __init__.py); do \
		cp -v docs/module.rst.template docs/modules/labm8.$${module%.py}.rst; \
		sed -i "s/@MODULE@/labm8.$${module%.py}/g" docs/modules/labm8.$${module%.py}.rst; \
		sed -i "s/@MODULE_UNDERLINE@/$$(head -c $$(echo labm8.$${module%.py} | wc -c) < /dev/zero | tr '\0' '=')/" docs/modules/labm8.$${module%.py}.rst; \
	done
	$(env3)$(MAKE) -C docs html

# help text
.PHONY: help
help:
	@echo "make test      Run unit tests in virtualenv"
	@echo "make clean     Remove virtualenvs"
	@echo "make install   Install globally"
