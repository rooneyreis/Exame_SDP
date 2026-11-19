.PHONY: certs keys up down seed test

certs:
	./scripts/gen-certs.sh

keys:
	./scripts/gen-keys.sh

up:
	docker compose up -d --build --wait

seed:
	./scripts/seed.sh

down:
	docker compose --profile nfs-test --profile tools down

test:
	./scripts/test.sh
