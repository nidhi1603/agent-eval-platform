"""Launch each trial attempt as its own Kubernetes Job and read back how it ended."""

from typing import Literal

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from app.settings import Settings

COMPONENT_LABEL = "app.kubernetes.io/component"
TRIAL_LABEL = "aep/trial-id"

JobState = Literal["active", "succeeded", "failed", "deadline", "missing"]


def job_name(trial_id: int, attempt: int) -> str:
    return f"trial-{trial_id}-a{attempt}"


def build_job_manifest(
    name: str, trial_id: int, attempt: int, callback_token: str, s: Settings, deadline_seconds: int | None = None
) -> dict:
    """One isolated pod per attempt: resource-capped, non-root, read-only root FS, no k8s API token."""
    labels = {COMPONENT_LABEL: "trial", TRIAL_LABEL: str(trial_id)}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "backoffLimit": 0,  # retries are decided by the platform, per attempt, not by Kubernetes
            "activeDeadlineSeconds": deadline_seconds or s.trial_deadline_seconds,
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
                                {"name": "AEP_ATTEMPT", "value": str(attempt)},
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

    def launch(self, name: str, trial_id: int, attempt: int, callback_token: str, deadline_seconds: int | None) -> None:
        body = build_job_manifest(name, trial_id, attempt, callback_token, self._s, deadline_seconds)
        try:
            self._batch.create_namespaced_job(self._s.namespace, body)
        except ApiException as e:
            if e.status != 409:  # 409 = this attempt's Job already exists; launching is idempotent
                raise

    def job_state(self, name: str) -> JobState:
        try:
            job = self._batch.read_namespaced_job(name, self._s.namespace)
        except ApiException as e:
            if e.status == 404:
                return "missing"
            raise
        for cond in job.status.conditions or []:
            if cond.status != "True":
                continue
            if cond.type == "Failed":
                return "deadline" if cond.reason == "DeadlineExceeded" else "failed"
            if cond.type == "Complete":
                return "succeeded"
        return "active"
