# Shortcuts for the docker compose dev setup. Run `make help` to list them.
# (No make on Windows? Copy the command after the colon-line into your terminal.)
DC = docker compose
RUN = $(DC) run --rm api

.PHONY: help up down build logs migrate migrations test seed shell dbshell superuser reset

help:          ## List commands
	@grep -E '^[a-z]+:.*##' Makefile | sed 's/:.*##/\t/'

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
