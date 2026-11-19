.PHONY: certs keys up down test nfs-test

certs:
	./scripts/gen-certs.sh

keys:
	./scripts/gen-keys.sh

up:
	docker compose up -d --build

down:
	docker compose --profile nfs-test down

test:
	./scripts/test.sh
