from app.k8s import build_job_manifest
from app.settings import Settings


def test_trial_job_is_isolated_and_capped():
    s = Settings(trial_image="agent-eval:test", api_url="http://api:8000", trial_cpu_limit="250m")
    job = build_job_manifest("trial-42-a2", 42, 2, "tok", s, deadline_seconds=120)
    pod = job["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert job["metadata"]["name"] == "trial-42-a2"
    assert job["spec"]["backoffLimit"] == 0  # retries belong to the platform, per attempt
    assert job["spec"]["activeDeadlineSeconds"] == 120
    assert pod["automountServiceAccountToken"] is False  # no k8s API access from trial pods
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert container["resources"]["limits"]["cpu"] == "250m"
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env == {"AEP_TRIAL_ID": "42", "AEP_ATTEMPT": "2", "AEP_CALLBACK_TOKEN": "tok",
                   "AEP_API_URL": "http://api:8000"}
    assert not any("DATABASE" in name for name in env)  # trial pods never see DB credentials


def test_default_deadline_comes_from_settings():
    s = Settings(trial_deadline_seconds=900)
    assert build_job_manifest("j", 1, 1, "t", s)["spec"]["activeDeadlineSeconds"] == 900
