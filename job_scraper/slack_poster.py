from __future__ import annotations

import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import HeaderBlock, SectionBlock, DividerBlock
from slack_sdk.models.blocks.basic_components import PlainTextObject, MarkdownTextObject

from job_scraper.models import Job

class SlackPoster:
    client: WebClient

    def __init__(self, optional: bool = False):
        self.token = os.getenv("SLACK_TOKEN")

        if not self.token:
            if optional:
                self.client = None
                return
            raise ValueError("Missing SLACK_TOKEN in environment.")

        self.client = WebClient(token=self.token)

    def create_job_slack_message(self, job: Job):
        """
        Returns (text, blocks) for Slack chat_postMessage.
        """
        title = job.job_overview.title
        company = job.job_overview.company
        due_date = job.job_overview.delivery_date
        desc = job.description_summarised or job.description
        link = job.job_overview.job_uri

        # Slack API only allows a maximum of 3000 characters.
        # Limit it to 1000 to not make it too noisy.
        if len(desc) > 3000:
            desc = desc[:1000]

        main_text = f"Ny utlysning fra {job.platform}"
        blocks = [
            HeaderBlock(text=PlainTextObject(text=title)),
            SectionBlock(
                fields=[
                    MarkdownTextObject(text=f"*Kunde:*\n{company}"),
                    MarkdownTextObject(text=f"*Frist:*\n{due_date}"),
                    MarkdownTextObject(text=f"*Plattform:*\n{job.platform}"),
                ]
            ),
            DividerBlock(),
            SectionBlock(text=MarkdownTextObject(text=desc)),
            DividerBlock(),
            SectionBlock(text=MarkdownTextObject(text=f"<{link}|Gå til oppdraget>")),
        ]
        return main_text, blocks

    def post_job(self, job: Job, channel: str = "job-posting"):
        """
        Posts a single job to Slack.
        """
        text, blocks = self.create_job_slack_message(job)
        if self.client is None:
            return None

        try:
            response = self.client.chat_postMessage(
                channel=channel, text=text, blocks=blocks
            )
            return response
        except SlackApiError as e:
            print(f"Slack API Error: {e.response['error']}")

    def post_digest(self, payload: dict, channel: str = "job-posting"):
        if self.client is None:
            return None

        title = payload.get("title") or "Untitled opportunity"
        customer = payload.get("customer") or "Unknown customer"
        deadline = payload.get("deadline") or "Unknown deadline"
        source_count = payload.get("source_count", 0)
        confidence = payload.get("confidence", 0)
        review_status = payload.get("review_status", "needs_review")
        cluster_id = payload.get("cluster_id")
        role_category = payload.get("role_category") or "generalist"
        relevance_score = payload.get("relevance_score", 0)
        text = f"KOIS digest: {title}"
        blocks = [
            HeaderBlock(text=PlainTextObject(text=f"KOIS: {title}")),
            SectionBlock(
                fields=[
                    MarkdownTextObject(text=f"*Kunde:*\n{customer}"),
                    MarkdownTextObject(text=f"*Frist:*\n{deadline}"),
                    MarkdownTextObject(text=f"*Kilder:*\n{source_count}"),
                    MarkdownTextObject(text=f"*Status:*\n{review_status}"),
                    MarkdownTextObject(text=f"*Confidence:*\n{confidence:.2f}"),
                    MarkdownTextObject(text=f"*Role:*\n{role_category}"),
                    MarkdownTextObject(text=f"*Relevance:*\n{relevance_score:.2f}"),
                    MarkdownTextObject(text=f"*Cluster ID:*\n{cluster_id}"),
                ]
            ),
        ]
        try:
            return self.client.chat_postMessage(channel=channel, text=text, blocks=blocks)
        except SlackApiError as e:
            print(f"Slack API Error: {e.response['error']}")



