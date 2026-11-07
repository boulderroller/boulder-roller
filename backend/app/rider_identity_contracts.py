"""Canonical public rider identity contract.

Public rider identity is the social/display envelope shared by feed,
notifications, comments, search, and rider profile surfaces. Wallets are
account/proof identifiers, not public rider display identity, so this contract
intentionally does not include a wallet field.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


PUBLIC_RIDER_REF_CONTRACT_VERSION = "public_rider_ref.v1"


class ViewerRelationship(str, Enum):
    self = "self"
    following = "following"
    none = "none"
    blocked = "blocked"


class PublicRiderRef(BaseModel):
    contract_version: str = Field(
        default=PUBLIC_RIDER_REF_CONTRACT_VERSION,
        alias="contractVersion",
    )
    id: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = Field(default=None, alias="displayName")
    avatar_url: Optional[str] = Field(default=None, alias="avatarUrl")
    is_public: Optional[bool] = Field(default=None, alias="isPublic")
    viewer_relationship: ViewerRelationship = Field(
        default=ViewerRelationship.none,
        alias="viewerRelationship",
    )

    model_config = {"populate_by_name": True, "by_alias": True, "extra": "ignore"}


def _first(row: Optional[dict[str, Any]], *keys: str) -> Any:
    if not row:
        return None
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_public_username(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    return text[1:].strip() if text.startswith("@") else text


def public_rider_ref(
    row: Optional[dict[str, Any]],
    *,
    fallback_id: Any = None,
    is_public: Optional[bool] = None,
    viewer_relationship: ViewerRelationship | str | None = None,
) -> PublicRiderRef:
    relationship = viewer_relationship or ViewerRelationship.none
    if not isinstance(relationship, ViewerRelationship):
        try:
            relationship = ViewerRelationship(str(relationship))
        except ValueError:
            relationship = ViewerRelationship.none

    explicit_public = is_public
    if explicit_public is None:
        row_value = _first(row, "is_public", "isPublic")
        explicit_public = bool(row_value) if row_value is not None else None

    display_name = _clean_text(_first(row, "display_name", "displayName"))
    avatar_url = _clean_text(_first(row, "avatar_url", "avatarUrl"))
    if explicit_public is False:
        display_name = None
        avatar_url = None

    return PublicRiderRef(
        id=_clean_text(_first(row, "id", "user_id", "userId") or fallback_id),
        username=clean_public_username(_first(row, "username")),
        display_name=display_name,
        avatar_url=avatar_url,
        is_public=explicit_public,
        viewer_relationship=relationship,
    )


def public_rider_ref_dict(
    row: Optional[dict[str, Any]],
    *,
    fallback_id: Any = None,
    is_public: Optional[bool] = None,
    viewer_relationship: ViewerRelationship | str | None = None,
) -> dict[str, Any]:
    return public_rider_ref(
        row,
        fallback_id=fallback_id,
        is_public=is_public,
        viewer_relationship=viewer_relationship,
    ).model_dump(by_alias=True)


def rider_route_identifier(row: Optional[dict[str, Any]]) -> Optional[str]:
    """Public route identifier preference: username, then opaque user id."""
    return clean_public_username(_first(row, "username")) or _clean_text(_first(row, "id", "user_id", "userId"))
