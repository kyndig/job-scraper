import os
from typing import List
from job_scraper.models import Job, JobListModel

class NewJobPostDetector:
    """
    Loads known jobs (from a JSON file), compares them with newly scraped
    ones, and helps you figure out which are new.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.known_jobs: List[Job] = []

        if os.path.isfile(self.file_path):
            with open(self.file_path, "r") as f:
                contents = f.read()
                self.known_jobs = JobListModel.validate_json(contents)

        # We'll store known IDs in a set for quick membership checks
        self.known_ids = {t.job_id for t in self.known_jobs}

    def detect_new_jobs(self, scraped_jobs: List[Job]) -> List[Job]:
        """
        Returns a sublist of `scraped_jobs` whose IDs
        do not appear in `self.known_ids`.
        """
        new_ones = [t for t in scraped_jobs if t.job_id not in self.known_ids]
        return new_ones

    def update_known_jobs(self, new_jobs: List[Job]) -> None:
        """
        Adds the newly scraped jobs to our known list
        (if they're not already known) and writes them to disk.
        """
        updated = False
        for t in new_jobs:
            if t.job_id not in self.known_ids:
                self.known_jobs.append(t)
                self.known_ids.add(t.job_id)
                updated = True

        if updated:
            # Write out the updated list to disk
            json_bytes = JobListModel.dump_json(self.known_jobs, indent=4)
            with open(self.file_path, "wb") as f:
                f.write(json_bytes)



