"""Pydantic v2 response schemas for the Admin Undo/Redo audit feature."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogEntryResponse(BaseModel):
    """A single audit log entry as returned by GET /api/admin/changes."""

    id: UUID
    admin_id: UUID | None
    action_type: str
    resource_type: str
    resource_id: str
    book_slug: str
    old_value: dict[str, Any]
    new_value: dict[str, Any]
    affected_count: int
    created_at: datetime
    undone_at: datetime | None
    undone_by: UUID | None
    redo_of: UUID | None

    model_config = {"from_attributes": True}


class UndoResponse(BaseModel):
    """Response body returned by POST /api/admin/changes/{audit_id}/undo."""

    success: bool
    message: str
    audit_id: UUID
    action_type: str


class RedoResponse(BaseModel):
    """Response body returned by POST /api/admin/changes/{audit_id}/redo."""

    success: bool
    message: str
    original_audit_id: UUID
    new_audit_id: UUID
    action_type: str
