.PHONY: install
install:
	pip install -r requirements.txt
	pip install -r tests/requirements.txt

.PHONY: lint
lint:
	ruff check app/ tests/
	ruff format app/ tests/ --check

.PHONY: format
format:
	ruff check app/ tests/ --fix
	ruff format app/ tests/

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

.PHONY: restore-from-live
restore-from-live:
	heroku pg:backups:capture --app tc-hermes
	heroku pg:backups:download --app tc-hermes
	make reset-db && time pg_restore --clean --no-acl --no-owner -j12 -h localhost -U postgres -d hermes latest.dump
