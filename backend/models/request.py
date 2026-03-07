from pydantic import BaseModel, Field

class AnalysisRequest(BaseModel):
    company_name: str = Field(..., description="The name of the company to analyze")
