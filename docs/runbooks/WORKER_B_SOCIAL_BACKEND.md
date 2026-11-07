# Worker B: Social Features Backend

> **Priority:** P3
> **Estimated Scope:** 6 tasks
> **Dependencies:** None (independent workstream)
> **Branch:** `feat/social-features`

---

## Overview

Implement the social layer that drives viral growth and retention. Currently, the web portal has UI components (FollowingModal, FeedTab, CommentThread) but NO backend support.

---

## Tasks

### SOCIAL-301: Social Graph (Follows)

**Current:** FollowingModal UI exists but no backend

**Database Schema:**
```sql
-- backend/sql/018_social.sql

-- Follows table for social graph
CREATE TABLE follows (
    follower_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    following_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (follower_id, following_id),
    CHECK (follower_id != following_id)  -- Can't follow yourself
);

CREATE INDEX idx_follows_follower ON follows(follower_id);
CREATE INDEX idx_follows_following ON follows(following_id);

-- Denormalized counts for fast lookup
ALTER TABLE users ADD COLUMN IF NOT EXISTS follower_count INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS following_count INT DEFAULT 0;

-- Trigger to update counts
CREATE OR REPLACE FUNCTION update_follow_counts()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE users SET following_count = following_count + 1 WHERE id = NEW.follower_id;
        UPDATE users SET follower_count = follower_count + 1 WHERE id = NEW.following_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE users SET following_count = following_count - 1 WHERE id = OLD.follower_id;
        UPDATE users SET follower_count = follower_count - 1 WHERE id = OLD.following_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_follow_counts
AFTER INSERT OR DELETE ON follows
FOR EACH ROW EXECUTE FUNCTION update_follow_counts();
```

**Backend Implementation:**
```python
# backend/app/routes/social.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository
from ..schemas import UserProfilePublic

router = APIRouter(prefix="/social", tags=["social"])


@router.post("/follow/{user_id}")
async def follow_user(
    user_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Follow another user."""
    if str(user_id) == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself"
        )

    # Check target user exists
    target = await repo.get_user_by_id(str(user_id))
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if already following
    existing = await repo.get_follow(current_user.user_id, str(user_id))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already following this user"
        )

    await repo.create_follow(current_user.user_id, str(user_id))

    # Create notification for target user
    await repo.create_notification(
        user_id=str(user_id),
        notification_type="new_follower",
        title="New Follower",
        message=f"@{current_user.username or current_user.wallet[:8]} started following you",
        data={"follower_id": current_user.user_id}
    )

    return {"status": "followed", "following_id": str(user_id)}


@router.delete("/follow/{user_id}")
async def unfollow_user(
    user_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Unfollow a user."""
    deleted = await repo.delete_follow(current_user.user_id, str(user_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not following this user"
        )

    return {"status": "unfollowed", "unfollowed_id": str(user_id)}


@router.get("/followers/{user_id}", response_model=List[UserProfilePublic])
async def get_followers(
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get list of users following the specified user."""
    followers = await repo.get_followers(str(user_id), limit=limit, offset=offset)
    return followers


@router.get("/following/{user_id}", response_model=List[UserProfilePublic])
async def get_following(
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get list of users the specified user is following."""
    following = await repo.get_following(str(user_id), limit=limit, offset=offset)
    return following


@router.get("/is-following/{user_id}")
async def check_is_following(
    user_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Check if current user is following the specified user."""
    is_following = await repo.get_follow(current_user.user_id, str(user_id))
    return {"is_following": is_following is not None}
```

**Repository Methods:**
```python
# backend/app/repositories.py (add these methods)

async def create_follow(self, follower_id: str, following_id: str) -> dict:
    result = await self._client.table("follows").insert({
        "follower_id": follower_id,
        "following_id": following_id
    }).execute()
    return result.data[0] if result.data else None

async def delete_follow(self, follower_id: str, following_id: str) -> bool:
    result = await self._client.table("follows").delete().match({
        "follower_id": follower_id,
        "following_id": following_id
    }).execute()
    return len(result.data) > 0

async def get_follow(self, follower_id: str, following_id: str) -> dict:
    result = await self._client.table("follows").select("*").match({
        "follower_id": follower_id,
        "following_id": following_id
    }).execute()
    return result.data[0] if result.data else None

async def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> list:
    result = await self._client.table("follows")\
        .select("follower_id, users!follows_follower_id_fkey(*)")\
        .eq("following_id", user_id)\
        .order("followed_at", desc=True)\
        .range(offset, offset + limit - 1)\
        .execute()
    return [row["users"] for row in result.data]

async def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> list:
    result = await self._client.table("follows")\
        .select("following_id, users!follows_following_id_fkey(*)")\
        .eq("follower_id", user_id)\
        .order("followed_at", desc=True)\
        .range(offset, offset + limit - 1)\
        .execute()
    return [row["users"] for row in result.data]
```

---

### SOCIAL-302: Activity Feed

**Database Schema:**
```sql
-- Activity feed for followed users' activities
CREATE TABLE activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,  -- 'ride', 'achievement', 'stake', 'follow', 'kom'
    target_type VARCHAR(50),  -- 'ride', 'segment', 'user'
    target_id UUID,
    title TEXT NOT NULL,
    description TEXT,
    metadata JSONB,
    is_public BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_activities_user ON activities(user_id);
CREATE INDEX idx_activities_created ON activities(created_at DESC);
CREATE INDEX idx_activities_type ON activities(activity_type);

-- Composite index for feed queries
CREATE INDEX idx_activities_feed ON activities(user_id, created_at DESC) WHERE is_public = TRUE;
```

**Backend Implementation:**
```python
# backend/app/routes/feed.py
from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from datetime import datetime

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("")
async def get_feed(
    limit: int = Query(20, le=100),
    before: Optional[datetime] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get activity feed from followed users.

    Returns activities from users the current user follows,
    ordered by most recent first.
    """
    # Get list of followed user IDs
    following = await repo.get_following_ids(current_user.user_id)

    if not following:
        return {
            "activities": [],
            "message": "Follow some riders to see their activities here!"
        }

    # Fetch activities from followed users
    activities = await repo.get_feed_activities(
        user_ids=following,
        limit=limit,
        before=before
    )

    # Enrich with user data
    enriched = []
    for activity in activities:
        user = await repo.get_user_by_id(activity["user_id"])
        enriched.append({
            **activity,
            "user": {
                "id": user["id"],
                "username": user.get("username"),
                "display_name": user.get("display_name"),
                "avatar_url": user.get("avatar_url"),
                "wallet": user.get("wallet", "")[:8] + "..."
            }
        })

    return {
        "activities": enriched,
        "has_more": len(activities) == limit
    }


@router.get("/global")
async def get_global_feed(
    limit: int = Query(20, le=100),
    before: Optional[datetime] = None,
    activity_type: Optional[str] = None,
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get global activity feed (public activities from all users).

    Optionally filter by activity type (ride, achievement, kom, etc.)
    """
    activities = await repo.get_global_activities(
        limit=limit,
        before=before,
        activity_type=activity_type
    )

    return {
        "activities": activities,
        "has_more": len(activities) == limit
    }


# Activity creation helper (called from other routes)
async def create_activity(
    repo: DatabaseRepository,
    user_id: str,
    activity_type: str,
    title: str,
    description: str = None,
    target_type: str = None,
    target_id: str = None,
    metadata: dict = None,
    is_public: bool = True
):
    """Helper function to create activities from other modules."""
    await repo.create_activity(
        user_id=user_id,
        activity_type=activity_type,
        title=title,
        description=description,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        is_public=is_public
    )
```

**Integration Points (add to existing routes):**

```python
# In backend/app/routes/rides.py - after ride completion
await create_activity(
    repo=repo,
    user_id=current_user.user_id,
    activity_type="ride",
    title=f"Completed a {distance_km:.1f}km ride",
    description=f"{elevation_m:.0f}m elevation • {tss:.0f} TSS",
    target_type="ride",
    target_id=ride_id,
    metadata={"distance_km": distance_km, "elevation_m": elevation_m, "tss": tss}
)

# In backend/app/services/achievement_detector.py - after achievement
await create_activity(
    repo=repo,
    user_id=user_id,
    activity_type="achievement",
    title=f"Unlocked: {achievement.title}",
    description=achievement.description,
    target_type="achievement",
    target_id=achievement.id,
    metadata={"achievement_type": achievement.achievement_type}
)

# In backend/app/routes/staking.py - after stake
await create_activity(
    repo=repo,
    user_id=current_user.user_id,
    activity_type="stake",
    title=f"Staked {amount} DUNG on {segment_name}",
    target_type="segment",
    target_id=segment_id,
    metadata={"amount": amount, "lp_tokens": lp_tokens}
)
```

---

### SOCIAL-303: Notifications System

**Database Schema:**
```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    data JSONB,
    read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_notifications_user ON notifications(user_id);
CREATE INDEX idx_notifications_unread ON notifications(user_id, read) WHERE read = FALSE;
CREATE INDEX idx_notifications_created ON notifications(created_at DESC);

-- Notification preferences
CREATE TABLE notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email_enabled BOOLEAN DEFAULT TRUE,
    push_enabled BOOLEAN DEFAULT TRUE,
    new_follower BOOLEAN DEFAULT TRUE,
    ride_completed BOOLEAN DEFAULT TRUE,
    achievement_unlocked BOOLEAN DEFAULT TRUE,
    kom_beaten BOOLEAN DEFAULT TRUE,
    staking_reward BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

**Backend Implementation:**
```python
# backend/app/routes/notifications.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from uuid import UUID

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get user's notifications."""
    notifications = await repo.get_user_notifications(
        user_id=current_user.user_id,
        limit=limit,
        unread_only=unread_only
    )

    unread_count = await repo.get_unread_notification_count(current_user.user_id)

    return {
        "notifications": notifications,
        "unread_count": unread_count
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Mark a notification as read."""
    success = await repo.mark_notification_read(
        notification_id=str(notification_id),
        user_id=current_user.user_id
    )

    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"status": "read"}


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Mark all notifications as read."""
    count = await repo.mark_all_notifications_read(current_user.user_id)
    return {"status": "read", "count": count}


@router.get("/preferences")
async def get_notification_preferences(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get user's notification preferences."""
    prefs = await repo.get_notification_preferences(current_user.user_id)
    return prefs or {
        "email_enabled": True,
        "push_enabled": True,
        "new_follower": True,
        "ride_completed": True,
        "achievement_unlocked": True,
        "kom_beaten": True,
        "staking_reward": True
    }


@router.put("/preferences")
async def update_notification_preferences(
    preferences: dict,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Update user's notification preferences."""
    updated = await repo.upsert_notification_preferences(
        user_id=current_user.user_id,
        preferences=preferences
    )
    return updated


# Notification creation helper
async def create_notification(
    repo: DatabaseRepository,
    user_id: str,
    notification_type: str,
    title: str,
    message: str = None,
    data: dict = None
):
    """
    Create a notification for a user.

    Checks user preferences before creating.
    """
    # Check user preferences
    prefs = await repo.get_notification_preferences(user_id)
    if prefs:
        pref_key = notification_type.replace("-", "_")
        if not prefs.get(pref_key, True):
            return None  # User disabled this notification type

    notification = await repo.create_notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=data
    )

    # TODO: Send push notification if enabled
    # TODO: Send email if enabled and significant

    return notification
```

---

### SOCIAL-304: Comments & Kudos

**Database Schema:**
```sql
-- Comments on rides/activities
CREATE TABLE comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type VARCHAR(50) NOT NULL,  -- 'ride', 'activity', 'segment_effort'
    target_id UUID NOT NULL,
    content TEXT NOT NULL,
    parent_id UUID REFERENCES comments(id) ON DELETE CASCADE,  -- For threading
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_comments_target ON comments(target_type, target_id);
CREATE INDEX idx_comments_user ON comments(user_id);

-- Kudos (likes/reactions)
CREATE TABLE kudos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type VARCHAR(50) NOT NULL,  -- 'ride', 'activity', 'comment'
    target_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, target_type, target_id)
);

CREATE INDEX idx_kudos_target ON kudos(target_type, target_id);

-- Denormalized kudos count
ALTER TABLE activities ADD COLUMN IF NOT EXISTS kudos_count INT DEFAULT 0;
```

**Backend Implementation:**
```python
# backend/app/routes/interactions.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

router = APIRouter(tags=["interactions"])


class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[UUID] = None


@router.post("/rides/{ride_id}/comments")
async def add_comment_to_ride(
    ride_id: UUID,
    comment: CommentCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Add a comment to a ride."""
    # Verify ride exists and is public
    ride = await repo.get_ride_by_id(str(ride_id))
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    created = await repo.create_comment(
        user_id=current_user.user_id,
        target_type="ride",
        target_id=str(ride_id),
        content=comment.content,
        parent_id=str(comment.parent_id) if comment.parent_id else None
    )

    # Notify ride owner
    if ride["user_id"] != current_user.user_id:
        await create_notification(
            repo=repo,
            user_id=ride["user_id"],
            notification_type="comment",
            title="New comment on your ride",
            message=f"@{current_user.username or 'Someone'}: {comment.content[:50]}...",
            data={"ride_id": str(ride_id), "comment_id": created["id"]}
        )

    return created


@router.get("/rides/{ride_id}/comments")
async def get_ride_comments(
    ride_id: UUID,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get all comments for a ride."""
    comments = await repo.get_comments("ride", str(ride_id))
    return {"comments": comments}


@router.post("/rides/{ride_id}/kudos")
async def give_kudos_to_ride(
    ride_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Give kudos to a ride."""
    ride = await repo.get_ride_by_id(str(ride_id))
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    # Check if already gave kudos
    existing = await repo.get_kudos(current_user.user_id, "ride", str(ride_id))
    if existing:
        raise HTTPException(status_code=400, detail="Already gave kudos")

    await repo.create_kudos(current_user.user_id, "ride", str(ride_id))

    # Update kudos count
    await repo.increment_kudos_count("ride", str(ride_id))

    # Notify ride owner
    if ride["user_id"] != current_user.user_id:
        await create_notification(
            repo=repo,
            user_id=ride["user_id"],
            notification_type="kudos",
            title="Someone gave you kudos!",
            message=f"@{current_user.username or 'A rider'} liked your ride",
            data={"ride_id": str(ride_id)}
        )

    return {"status": "kudos_given"}


@router.delete("/rides/{ride_id}/kudos")
async def remove_kudos_from_ride(
    ride_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Remove kudos from a ride."""
    deleted = await repo.delete_kudos(current_user.user_id, "ride", str(ride_id))
    if deleted:
        await repo.decrement_kudos_count("ride", str(ride_id))
    return {"status": "kudos_removed"}
```

---

## Testing Instructions

### Unit Tests

```python
# backend/tests/test_social.py
import pytest
from uuid import uuid4


class TestFollows:
    async def test_follow_user(self, test_client, auth_headers, other_user):
        """Test following another user."""
        response = await test_client.post(
            f"/social/follow/{other_user.id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["status"] == "followed"

    async def test_cannot_follow_self(self, test_client, auth_headers, current_user):
        """Test that users cannot follow themselves."""
        response = await test_client.post(
            f"/social/follow/{current_user.id}",
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "yourself" in response.json()["detail"].lower()

    async def test_cannot_follow_twice(self, test_client, auth_headers, other_user):
        """Test that duplicate follows are rejected."""
        # First follow
        await test_client.post(f"/social/follow/{other_user.id}", headers=auth_headers)

        # Second follow should fail
        response = await test_client.post(
            f"/social/follow/{other_user.id}",
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    async def test_unfollow_user(self, test_client, auth_headers, other_user):
        """Test unfollowing a user."""
        # First follow
        await test_client.post(f"/social/follow/{other_user.id}", headers=auth_headers)

        # Then unfollow
        response = await test_client.delete(
            f"/social/follow/{other_user.id}",
            headers=auth_headers
        )
        assert response.status_code == 200

    async def test_get_followers(self, test_client, auth_headers, other_user, third_user):
        """Test getting user's followers."""
        # Have other users follow current user
        # ... setup ...

        response = await test_client.get(f"/social/followers/{current_user.id}")
        assert response.status_code == 200
        followers = response.json()
        assert isinstance(followers, list)


class TestFeed:
    async def test_empty_feed_when_not_following(self, test_client, auth_headers):
        """Test that feed is empty when not following anyone."""
        response = await test_client.get("/feed", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["activities"] == []
        assert "follow" in response.json()["message"].lower()

    async def test_feed_shows_followed_activities(self, test_client, auth_headers, other_user):
        """Test that feed shows activities from followed users."""
        # Follow other user
        await test_client.post(f"/social/follow/{other_user.id}", headers=auth_headers)

        # Create activity for other user
        await create_test_activity(other_user.id, "ride", "Test ride")

        # Check feed
        response = await test_client.get("/feed", headers=auth_headers)
        assert response.status_code == 200
        activities = response.json()["activities"]
        assert len(activities) > 0
        assert activities[0]["user"]["id"] == str(other_user.id)


class TestNotifications:
    async def test_follow_creates_notification(self, test_client, auth_headers, other_user):
        """Test that following creates a notification for the followed user."""
        await test_client.post(f"/social/follow/{other_user.id}", headers=auth_headers)

        # Check other user's notifications
        notifications = await get_user_notifications(other_user.id)
        assert any(n["notification_type"] == "new_follower" for n in notifications)

    async def test_mark_notification_read(self, test_client, auth_headers):
        """Test marking notification as read."""
        # Create a notification
        notification = await create_test_notification(current_user.id)

        response = await test_client.post(
            f"/notifications/{notification['id']}/read",
            headers=auth_headers
        )
        assert response.status_code == 200

    async def test_mark_all_read(self, test_client, auth_headers):
        """Test marking all notifications as read."""
        # Create multiple notifications
        await create_test_notification(current_user.id)
        await create_test_notification(current_user.id)

        response = await test_client.post("/notifications/read-all", headers=auth_headers)
        assert response.status_code == 200

        # Verify all are read
        notifications = await test_client.get(
            "/notifications?unread_only=true",
            headers=auth_headers
        )
        assert len(notifications.json()["notifications"]) == 0


class TestKudos:
    async def test_give_kudos(self, test_client, auth_headers, other_user_ride):
        """Test giving kudos to a ride."""
        response = await test_client.post(
            f"/rides/{other_user_ride.id}/kudos",
            headers=auth_headers
        )
        assert response.status_code == 200

    async def test_cannot_give_kudos_twice(self, test_client, auth_headers, other_user_ride):
        """Test that duplicate kudos are rejected."""
        await test_client.post(f"/rides/{other_user_ride.id}/kudos", headers=auth_headers)

        response = await test_client.post(
            f"/rides/{other_user_ride.id}/kudos",
            headers=auth_headers
        )
        assert response.status_code == 400

    async def test_remove_kudos(self, test_client, auth_headers, other_user_ride):
        """Test removing kudos."""
        await test_client.post(f"/rides/{other_user_ride.id}/kudos", headers=auth_headers)

        response = await test_client.delete(
            f"/rides/{other_user_ride.id}/kudos",
            headers=auth_headers
        )
        assert response.status_code == 200
```

### Manual Testing Checklist

```markdown
## Social Features Manual Testing Checklist

### Following
- [ ] Follow a user → Verify appears in their followers list
- [ ] Unfollow a user → Verify removed from their followers list
- [ ] Try to follow yourself → Verify error message
- [ ] Try to follow same user twice → Verify error message
- [ ] Check /social/is-following → Verify correct response
- [ ] Check follower/following counts update correctly

### Activity Feed
- [ ] Follow no one → Verify empty feed with helpful message
- [ ] Follow users → Verify their activities appear in feed
- [ ] Create a ride → Verify activity appears in followers' feeds
- [ ] Unlock achievement → Verify activity created
- [ ] Check global feed → Verify public activities shown
- [ ] Test pagination → Verify "has_more" works correctly

### Notifications
- [ ] Get followed → Verify notification received
- [ ] Get kudos on ride → Verify notification received
- [ ] Get comment on ride → Verify notification received
- [ ] Mark single notification read → Verify updated
- [ ] Mark all notifications read → Verify all updated
- [ ] Update preferences → Verify preferences saved
- [ ] Disable notification type → Verify not received

### Comments & Kudos
- [ ] Add comment to ride → Verify comment appears
- [ ] Reply to comment (threading) → Verify parent_id works
- [ ] Give kudos → Verify kudos count increments
- [ ] Remove kudos → Verify kudos count decrements
- [ ] View comments list → Verify sorted by date

### Edge Cases
- [ ] Follow/unfollow rapidly → Verify no race conditions
- [ ] Very long comment → Verify length limit enforced
- [ ] Comment on private ride → Verify access control
- [ ] Notification for deleted user → Verify graceful handling
```

---

## Success Criteria

- [ ] Users can follow/unfollow other users
- [ ] Activity feed shows activities from followed users
- [ ] Notifications created for relevant events
- [ ] Notification preferences respected
- [ ] Comments can be added to rides
- [ ] Kudos system working (give/remove)
- [ ] Follower/following counts accurate
- [ ] All unit tests pass
- [ ] Manual testing checklist complete

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `backend/sql/018_social.sql` | NEW - Social tables |
| `backend/app/routes/social.py` | NEW - Follow endpoints |
| `backend/app/routes/feed.py` | NEW - Feed endpoints |
| `backend/app/routes/notifications.py` | NEW - Notification endpoints |
| `backend/app/routes/interactions.py` | NEW - Comments/kudos |
| `backend/app/repositories.py` | Add social methods |
| `backend/app/routes/rides.py` | Add activity creation |
| `backend/app/main.py` | Register new routers |
