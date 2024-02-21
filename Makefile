PYTHON?=python
SOURCES=hdeps setup.py scripts

.PHONY: venv
venv:
	$(PYTHON) -m venv .venv
	source .venv/bin/activate && make setup
	@echo 'run `source .venv/bin/activate` to use virtualenv'

# The rest of these are intended to be run within the venv, where python points
# to whatever was used to set up the venv.

.PHONY: setup
setup:
	python -m pip install -Ue .[dev,test]

.PHONY: test
test:
	python -m coverage run -m hdeps.tests $(TESTOPTS)
	python -m coverage report

.PHONY: format
format:
	python -m ufmt format $(SOURCES)

.PHONY: lint
lint:
	python -m ufmt check $(SOURCES)
	python -m flake8 $(SOURCES)
	# TODO: Excludes don't appear to work right on Windows, which is why setuptools is also in allow-names
	python -m checkdeps --excludes 'hdeps/tests/demo_project/*.py' --metadata-extras test --allow-names hdeps,setuptools hdeps
	mypy --strict --install-types --non-interactive hdeps

.PHONY: release
release:
	rm -rf dist
	python setup.py sdist bdist_wheel
	twine upload dist/*
