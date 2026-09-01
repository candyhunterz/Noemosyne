"""Versioned public request and response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalCreate(ApiModel):
    namespace_id: str
    proposer_actor_id: str
    title: str = Field(min_length=1, max_length=400)
    description: str = ""
    base_revision_token: int = Field(ge=0)


class ProposalItemCreate(ApiModel):
    command_type: str
    payload: dict[str, Any]
    preconditions: dict[str, Any] = Field(default_factory=dict)


class ReviewCreate(ApiModel):
    proposal_item_id: str
    reviewer_actor_id: str
    decision: Literal["accept", "reject", "request_changes", "abstain"]
    rationale: str = Field(min_length=1)


class ApplyRequest(ApiModel):
    applied_by_actor_id: str


class SearchRequest(ApiModel):
    namespace_id: str
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    verdicts: list[str] = Field(default_factory=list)


class GraphTraceRequest(ApiModel):
    start_claim_id: str
    relation_types: set[str]
    max_depth: int = Field(default=3, ge=0, le=3)
    max_nodes: int = Field(default=100, ge=1, le=100)


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: str | None = None
