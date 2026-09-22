import time

from map_cutout.jobs import JobManager


def wait(manager, job_id):
    for _ in range(100):
        job = manager.status(job_id)
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_jobs_run_one_at_a_time_and_return_results():
    manager = JobManager(max_workers=1)
    first = manager.submit(lambda: 42)
    assert wait(manager, first)["result"] == 42
    assert manager.status(first)["progress"] == 1.0


def test_job_errors_are_translated_to_chinese():
    manager = JobManager(max_workers=1)

    def fail():
        raise RuntimeError("CUDA out of memory")

    job = wait(manager, manager.submit(fail))
    assert job["state"] == "failed"
    assert "显存不足" in job["message"]

