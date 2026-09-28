CLUSTER := aep
RELEASE := aep
IMAGE   := agent-eval:dev
CHART   := deploy/helm/agent-eval

.PHONY: test cluster image load deploy up smoke logs down bench-mock demo

test:
	uv run pytest -q

# One dev task through the real tau2 path with scripted model responses: no network, no spend.
bench-mock:
	uv run --extra bench python -m bench.run --task task_015 --retrieval-config bm25 \
		--scripted bench/scripts/task_015_reference.json

# The project's evidence trail from saved artifacts: pins, benchmark exposure, one failure end to end, results. $0.
demo:
	uv run --extra bench python -m bench.demo

cluster:
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config deploy/kind/cluster.yaml

image:
	docker build -t $(IMAGE) .

load: image
	kind load docker-image $(IMAGE) --name $(CLUSTER)

deploy:
	helm upgrade --install $(RELEASE) $(CHART) --wait --timeout 5m
	kubectl rollout restart deploy/$(RELEASE)-api deploy/$(RELEASE)-dispatcher
	kubectl rollout status deploy/$(RELEASE)-api --timeout 120s
	kubectl rollout status deploy/$(RELEASE)-dispatcher --timeout 120s

up: cluster load deploy

smoke:
	./scripts/smoke.sh

logs:
	kubectl logs deploy/$(RELEASE)-dispatcher --tail=50

down:
	kind delete cluster --name $(CLUSTER)
