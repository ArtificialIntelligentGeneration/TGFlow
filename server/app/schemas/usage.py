from pydantic import BaseModel, Field


class ReserveRequest(BaseModel):
    messages: int = Field(gt=0)
    correlation_id: str


class ReserveResponse(BaseModel):
    reservation_id: str
    reserved: int
    remaining: int


class CommitRequest(BaseModel):
    reservation_id: str
    used: int


class RollbackRequest(BaseModel):
    reservation_id: str



