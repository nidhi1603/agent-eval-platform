"""Launch each trial as its own Kubernetes Job."""

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.settings import Settings

COMPONENT_LABEL = "app.kubernetes.io/component"
TRIAL_LABEL = "aep/trial-id"


def job_name(trial_id: int) -> str:
    return f"trial-{trial_id}"


def build_job_manifest(trial_id: int, callback_token: str, s: Settings) -> dict:
    """One isolated pod per trial: resource-capped, non-root, read-only root FS, no k8s API token."""
    labels = {COMPONENT_LABEL: "trial", TRIAL_LABEL: str(trial_id)}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name(trial_id), "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": s.trial_deadline_seconds,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "trial",
                            "image": s.trial_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-m", "worker.trial"],
                            "env": [
                                {"name": "AEP_TRIAL_ID", "value": str(trial_id)},
                                {"name": "AEP_CALLBACK_TOKEN", "value": callback_token},
                                {"name": "AEP_API_URL", "value": s.api_url},
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": s.trial_cpu_limit, "memory": s.trial_memory_limit},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                        }
                    ],
                    "volumes": [{"name": "tmp", "emptyDir": {}}],
                },
            },
        },
    }


class JobLauncher:
    def __init__(self, s: Settings):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._batch = client.BatchV1Api()
        self._s = s

    def active_count(self) -> int:
        jobs = self._batch.list_namespaced_job(
            self._s.namespace, label_selector=f"{COMPONENT_LABEL}=trial"
        ).items
        return sum(1 for j in jobs if not (j.status.succeeded or j.status.failed))

    def launch(self, trial_id: int, callback_token: str) -> None:
        body = build_job_manifest(trial_id, callback_token, self._s)
        try:
            self._batch.create_namespaced_job(self._s.namespace, body)
        except ApiException as e:
            if e.status != 409:  # 409 = already launched; relaunch is a no-op
                raise
