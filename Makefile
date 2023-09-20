.PHONY: install
install:
	pip install -r requirements.txt
	pip install -r tests/requirements.txt

.PHONY: lint
lint:
	ruff check app/ tests/
	black --check app tests

.PHONY: format
format:
	black app tests

.PHONY: test
test:
	pytest --cov=app

.PHONY: reset-db
reset-db:
	psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS hermes"
	psql -h localhost -U postgres -c "CREATE DATABASE hermes"

.PHONY: install-dev
install-dev:
	pip install -r requirements.txt
	pip install -r tests/requirements.txt
	pip install devtools
