"""Entrypoint for a trial pod: check in, run the agent, report the result."""

import logging
import os
import sys

import httpx

from worker.agents import AGENTS

log = logging.getLogger("trial")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    trial_id = int(os.environ["AEP_TRIAL_ID"])
    headers = {"x-trial-token": os.environ["AEP_CALLBACK_TOKEN"]}

    with httpx.Client(base_url=os.environ["AEP_API_URL"], headers=headers, timeout=30) as api:
        resp = api.post(f"/trials/{trial_id}/start")
        if resp.status_code == 409:
            # This attempt was superseded or the trial already finished: do not run the task again.
            log.info("trial %s: not running (%s)", trial_id, resp.json().get("detail"))
            return 0
        spec = resp.raise_for_status().json()
        log.info("trial %s attempt %s: agent=%s task=%s", trial_id, spec["attempt"], spec["agent"], spec["task_id"])
        try:
            agent = AGENTS[spec["agent"]]
            result = {"status": "completed", **agent(spec)}
        except Exception as e:
            log.exception("trial %s errored", trial_id)
            result = {"status": "errored", "error": repr(e)[:4000]}
        # If this post fails, the pod exits non-zero and the reconciler treats it as an infra failure.
        api.post(f"/trials/{trial_id}/result", json=result).raise_for_status()

    log.info("trial %s: %s", trial_id, result)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
