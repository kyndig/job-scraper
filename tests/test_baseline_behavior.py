from job_scraper.models import Job, JobOverview
from job_scraper.new_job_detector import NewJobPostDetector
from job_scraper.slack_poster import SlackPoster


def _job(uri: str) -> Job:
    return Job(
        job_overview=JobOverview(
            title="Senior Python Developer",
            company="Acme",
            description="Description",
            delivery_date="2026-06-20",
            job_uri=uri,
        ),
        description="Need a senior Python developer",
        platform="Mercell",
    )


def test_new_job_detector_detects_only_unknown_jobs(tmp_path):
    detector = NewJobPostDetector(str(tmp_path / "jobs.json"))
    first = _job("https://example.com/a")
    second = _job("https://example.com/b")
    detector.update_known_jobs([first])

    fresh_detector = NewJobPostDetector(str(tmp_path / "jobs.json"))
    new_jobs = fresh_detector.detect_new_jobs([first, second])

    assert len(new_jobs) == 1
    assert new_jobs[0].job_id == "https://example.com/b"


def test_slack_message_generation_is_stable():
    poster = SlackPoster(optional=True)
    text, blocks = poster.create_job_slack_message(_job("https://example.com/a"))
    assert "Ny utlysning" in text
    assert blocks[0].text.text == "Senior Python Developer"
