black = black -S -l 120
isort = isort -w 120

.PHONY: install
install:
	pip install -r requirements.txt
	pip install -r tests/requirements.txt

.PHONY: format
format:
	$(isort) app/
	$(isort) tests/
	$(black) app/ tests/

.PHONY: lint
lint:
	flake8 app/ tests/
	$(isort) --check-only app
	$(isort) --check-only tests
	$(black) --check app tests

.PHONY: test
test:
	pytest --cov=app

.PHONY: reset-db
reset-db:
	psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS hermes"
	psql -h localhost -U postgres -c "CREATE DATABASE hermes"
