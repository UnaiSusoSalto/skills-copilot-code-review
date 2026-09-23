"""
Announcement endpoints for the High School Management System API
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD date string, raising ValueError on bad input"""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Dates must be in YYYY-MM-DD format")


class AnnouncementInput(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    start_date: Optional[str] = None
    expiration_date: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be empty")
        return value

    @field_validator("expiration_date")
    @classmethod
    def expiration_is_valid_date(cls, value: str) -> str:
        _parse_date(value)
        return value

    @field_validator("start_date")
    @classmethod
    def start_is_valid_date(cls, value: Optional[str]) -> Optional[str]:
        if value:
            _parse_date(value)
        return value


def _require_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Ensure the request is made by a signed in teacher"""
    if not teacher_username:
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(
            status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "start_date": doc.get("start_date"),
        "expiration_date": doc["expiration_date"],
        "created_by": doc.get("created_by")
    }


def _is_active(doc: Dict[str, Any], today: date) -> bool:
    if _parse_date(doc["expiration_date"]) < today:
        return False

    start_date = doc.get("start_date")
    if start_date and _parse_date(start_date) > today:
        return False

    return True


def _validate_date_range(announcement: AnnouncementInput) -> None:
    if announcement.start_date and announcement.start_date > announcement.expiration_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be on or before the expiration date")


def _to_object_id(announcement_id: str) -> ObjectId:
    try:
        return ObjectId(announcement_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Announcement not found")


@router.get("/active", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements currently visible to everyone"""
    today = date.today()
    active = [
        _serialize(doc)
        for doc in announcements_collection.find()
        if _is_active(doc, today)
    ]
    active.sort(key=lambda item: item["expiration_date"])
    return active


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get every announcement - requires a signed in teacher"""
    _require_teacher(teacher_username)

    announcements = [_serialize(doc) for doc in announcements_collection.find()]
    announcements.sort(key=lambda item: item["expiration_date"])
    return announcements


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement - requires a signed in teacher"""
    teacher = _require_teacher(teacher_username)
    _validate_date_range(announcement)

    doc = {
        "message": announcement.message,
        "start_date": announcement.start_date,
        "expiration_date": announcement.expiration_date,
        "created_by": teacher["username"]
    }
    result = announcements_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement - requires a signed in teacher"""
    _require_teacher(teacher_username)
    _validate_date_range(announcement)

    updated = announcements_collection.find_one_and_update(
        {"_id": _to_object_id(announcement_id)},
        {"$set": {
            "message": announcement.message,
            "start_date": announcement.start_date,
            "expiration_date": announcement.expiration_date
        }},
        return_document=ReturnDocument.AFTER
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return _serialize(updated)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement - requires a signed in teacher"""
    _require_teacher(teacher_username)

    result = announcements_collection.delete_one(
        {"_id": _to_object_id(announcement_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
