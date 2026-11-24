# Shortcuts for the docker compose dev setup. Run `make help` to list them.
# (No make on Windows? Copy the command after the colon-line into your terminal.)
DC = docker compose
RUN = $(DC) run --rm api
# Same, but connected to Supabase (needs SUPABASE_DATABASE_URL in .env). For one-off admin tasks only.
SUPA = $(DC) run --rm -e DATABASE_TARGET=supabase api

.PHONY: help up down build logs migrate migrations test seed shell dbshell superuser reset checkdb supabase-check supabase-superuser

help:          ## List commands
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/'

up:            ## Start db + api (http://localhost:8000)
	$(DC) up --build

down:          ## Stop containers (keeps database data)
	$(DC) down

build:         ## Rebuild the api image (after changing requirements.txt)
	$(DC) build api

logs:          ## Follow api logs
	$(DC) logs -f api

migrate:       ## Apply migrations
	$(RUN) python manage.py migrate

migrations:    ## Create migrations after changing models
	$(RUN) python manage.py makemigrations

test:          ## Run the test suite
	$(RUN) python manage.py test

seed:          ## Load demo plants, users and sightings
	$(RUN) python manage.py seed_demo

shell:         ## Django shell
	$(RUN) python manage.py shell

dbshell:       ## psql into the local database
	$(DC) exec db psql -U bloom -d bloom

superuser:     ## Create an admin login for /admin/
	$(RUN) python manage.py createsuperuser

reset:         ## Wipe the local database and uploaded photos
	$(DC) down -v
	rm -rf media

checkdb:       ## Check the local database (extensions, migrations, RLS)
	$(RUN) python manage.py check_db

supabase-check: ## Check the Supabase database (read-only)
	$(SUPA) python manage.py check_db

supabase-superuser: ## Create an admin login on Supabase (production)
	$(SUPA) python manage.py createsuperuser
