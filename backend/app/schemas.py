from pydantic import BaseModel, Field, HttpUrl


class SourceReference(BaseModel):
    url: HttpUrl
    title: str | None = None


class WorkflowRequest(BaseModel):
    task: str = Field(min_length=3, max_length=1_000)


class WorkflowResponse(BaseModel):
    research: str
    analysis: str


class ExecutionResponse(BaseModel):
    task_id: str
    status: str
    research: str
    analysis: str
    report: str
    review: str
    sources: list[SourceReference] = Field(default_factory=list)
    total_tokens: int | None = None
    estimated_cost: float | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ExecutionRecord(BaseModel):
    id: str
    status: str
    task: str
    created_at: str
    elapsed_ms: int | None = None
    error: str | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    stages: list[dict] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    agents: int
    web_search_enabled: bool
    completed: int
    failed: int
    workflows: int
    token_usage: int | None = None
    estimated_cost: float | None = None
    provider: str
    model: str
    history: list[ExecutionRecord]


class TaskDetail(BaseModel):
    id: str
    task: str
    status: str
    created_at: str
    completed_at: str | None = None
    elapsed_ms: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    result: dict | None = None
    error: str | None = None
    stages: list[dict] = Field(default_factory=list)

