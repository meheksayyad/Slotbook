.PHONY: install migrations migrate setup run worker beat seed test cov lint up down
install:      ## create venv + install deps
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
migrations:   ## generate migrations (commit the result!)
	python manage.py makemigrations accounts venues bookings payments
migrate:
	python manage.py migrate
setup: migrations migrate seed
run:
	python manage.py runserver
worker:
	celery -A config worker -l info
beat:
	celery -A config beat -l info
seed:
	python manage.py seed_demo
test:
	pytest
cov:
	pytest --cov=apps --cov-report=term-missing
lint:
	ruff check .
up:
	docker compose up --build
down:
	docker compose down
