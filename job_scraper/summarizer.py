import os
from google import genai
from google.genai import types


class JobDescriptionSummarizer:
    system_instruction: str = """
        Your job is to summarize job descriptions and make it easy to understand the requirements of the job and what it is about.
        You will make bullet points when listing out requirements, and will format the summary in a nice and simple manner.
        Make the summary in the same language as the job description. If it is in Norwegian the summary is in Norwegian, and
        if it's in English then the summary is in English.
        Keep the summary under 1500 characters.

        Use markdown for Slack as the formatting for the summary. Use one * instead of two when doing bold headlines.
    """

    def __init__(self, optional: bool = False):
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            if optional:
                self.client = None
                return
            raise ValueError("No GEMINI_API_KEY in environment")

        self.client = genai.Client(api_key=api_key)

    def summarize(self, description: str):
        if self.client is None:
            return None
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction
            ),
            contents=description,
        )
        return response.text


