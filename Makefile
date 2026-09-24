CLUSTER := aep
RELEASE := aep
IMAGE   := agent-eval:dev
CHART   := deploy/helm/agent-eval

.PHONY: test cluster image load deploy up smoke logs down

test:
	uv run pytest -q

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
