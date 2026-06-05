from __future__ import annotations

from pydantic import BaseModel, TypeAdapter, computed_field
from pydantic.dataclasses import dataclass


@dataclass
class JobOverview:
    title: str | None = None
    company: str | None = None
    description: str | None = None
    delivery_date: str | None = None
    job_uri: str | None = None


class Job(BaseModel):
    job_overview: JobOverview
    description: str
    description_summarised: str | None = None
    platform: str | None = None

    @computed_field
    def job_id(self) -> str:
        return self.job_overview.job_uri


JobList = list[Job]
JobListModel = TypeAdapter(JobList)
