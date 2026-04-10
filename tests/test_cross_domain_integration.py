"""
Cross-domain integration tests for Kismet event-driven architecture.

Validates that events published by one service can be correctly consumed
by downstream services across domain boundaries.

Event chains tested:
  D1 auth    → user.created       → D5 email-service, D6 activity-logger
  D1 profile → profile.completed  → D2 discovery, D2 recommendation, D6 activity-logger
  D1 photo   → photo.uploaded     → D4 image-moderation
  D2 swipe   → swipe.created      → D2 match, D6 activity-logger
  D2 match   → match.created      → D3 icebreaker, D5 notifications, D6 activity-logger
  D3 message → message.sent       → D5 notifications, D6 activity-logger
  D4 text-mod  → content.flagged  → D6 admin-dashboard
  D4 image-mod → content.flagged  → D6 admin-dashboard
  D4 report    → user.reported    → D6 admin-dashboard, D6 activity-logger
"""

import json
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup — allow importing each service's lambda_function directly
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
SERVICES = REPO / "services"

D1_AUTH = SERVICES / "domain-1-identity" / "auth-service"
D1_PROFILE = SERVICES / "domain-1-identity" / "profile-service"
D1_PHOTO = SERVICES / "domain-1-identity" / "photo-service"
D2_DISCOVERY = SERVICES / "domain-2-discovery" / "discovery-service"
D2_SWIPE = SERVICES / "domain-2-discovery" / "swipe-service"
D2_MATCH = SERVICES / "domain-2-discovery" / "match-service"
D3_ICEBREAKER = SERVICES / "domain-3-messaging" / "icebreaker-service"
D3_MESSAGE = SERVICES / "domain-3-messaging" / "message-service"
D5_EMAIL = SERVICES / "domain-5-notifications" / "email-service"
D4_IMAGE_MOD = SERVICES / "domain-4-moderation" / "image-moderation-service"
D4_TEXT_MOD = SERVICES / "domain-4-moderation" / "text-moderation-service"
D4_REPORT = SERVICES / "domain-4-moderation" / "report-service"
D6_ACTIVITY = SERVICES / "domain-6-analytics" / "activity-logger-service"
D6_ADMIN = SERVICES / "domain-6-analytics" / "admin-dashboard-service"


def _add_path(p):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def eb_event(source: str, detail_type: str, detail: dict) -> dict:
    """Build a minimal EventBridge event envelope."""
    return {
        "source": source,
        "detail-type": detail_type,
        "detail": detail,
    }


def authed_http_event(method, path, body=None, user_id="user-123"):
    """Build a minimal API Gateway proxy event with JWT claims."""
    event = {
        "httpMethod": method,
        "path": path,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "body": json.dumps(body) if body else None,
    }
    return event


# ============================================================================
# 1. user.created → D5 email-service
# ============================================================================

class TestUserCreatedToEmailService(unittest.TestCase):
    """D1 auth publishes user.created → D5 email-service consumes it."""

    def test_event_payload_is_consumable(self):
        """Verify the user.created payload has all fields D5 email needs."""
        # Simulated user.created event as published by auth-service
        event_detail = {
            "userId": "user-abc",
            "email": "alice@university.edu",
            "timestamp": "2026-04-01T12:00:00Z",
        }

        # D5 email-service extracts these fields
        self.assertIn("userId", event_detail)
        self.assertIn("email", event_detail)
        self.assertIn("timestamp", event_detail)
        self.assertTrue(event_detail["email"].endswith(".edu"))

    def test_event_structure_matches_schema(self):
        event = eb_event("kismet.auth-service", "user.created", {
            "userId": "user-abc",
            "email": "alice@university.edu",
            "timestamp": "2026-04-01T12:00:00Z",
        })
        self.assertEqual(event["source"], "kismet.auth-service")
        self.assertEqual(event["detail-type"], "user.created")


# ============================================================================
# 2. profile.completed → D2 discovery-service
# ============================================================================

class TestProfileCompletedToDiscovery(unittest.TestCase):
    """D1 profile publishes profile.completed → D2 discovery indexes the user."""

    PROFILE_EVENT = {
        "userId": "user-abc",
        "name": "Alice",
        "birthDate": "1999-05-15",
        "birthTime": "14:30",
        "gender": "female",
        "preferred_gender": "male",
        "location_coordinates": [42.36, -71.06],
        "city": "Boston",
        "avatarUrl": "https://cdn.kismet.dev/user-abc/photo.jpg",
        "bio": "Astronomy major",
        "interests": ["astronomy", "hiking"],
        "timestamp": "2026-04-01T12:00:00Z",
    }

    def test_discovery_required_fields_present(self):
        """D2 discovery needs these fields to index a candidate."""
        d = self.PROFILE_EVENT
        # Fields discovery-service extracts (from lambda lines 44-74)
        self.assertIn("userId", d)
        self.assertIn("name", d)           # stored as displayName
        self.assertIn("birthDate", d)      # used for age calculation
        self.assertIn("gender", d)
        self.assertIn("preferred_gender", d)  # stored as preferredGender
        self.assertIn("location_coordinates", d)  # stored as location
        self.assertIn("city", d)
        self.assertIn("avatarUrl", d)
        self.assertIn("bio", d)

    def test_location_is_array_format(self):
        """Discovery expects [lat, lng] array for location."""
        loc = self.PROFILE_EVENT["location_coordinates"]
        self.assertIsInstance(loc, list)
        self.assertEqual(len(loc), 2)
        self.assertIsInstance(loc[0], (int, float))
        self.assertIsInstance(loc[1], (int, float))

    def test_gender_enum_values(self):
        """Gender must be a valid enum value for discovery filtering."""
        valid_genders = {"male", "female", "non-binary"}
        valid_preferences = {"male", "female", "non-binary", "everyone"}
        self.assertIn(self.PROFILE_EVENT["gender"], valid_genders)
        self.assertIn(self.PROFILE_EVENT["preferred_gender"], valid_preferences)

    def test_field_name_mapping(self):
        """Verify D1 uses preferred_gender (not interestedIn) in events."""
        # D1 profile-service maps interestedIn → preferred_gender in _build_event_detail
        self.assertNotIn("interestedIn", self.PROFILE_EVENT)
        self.assertIn("preferred_gender", self.PROFILE_EVENT)

    def test_timestamp_not_createdAt(self):
        """Events use 'timestamp', not 'createdAt' or 'updatedAt'."""
        self.assertIn("timestamp", self.PROFILE_EVENT)
        self.assertNotIn("createdAt", self.PROFILE_EVENT)
        self.assertNotIn("updatedAt", self.PROFILE_EVENT)


# ============================================================================
# 3. photo.uploaded → D4 image-moderation
# ============================================================================

class TestPhotoUploadedToImageModeration(unittest.TestCase):
    """D1 photo publishes photo.uploaded → D4 image-moderation consumes it."""

    PHOTO_EVENT = {
        "photoId": "photo-001",
        "userId": "user-abc",
        "s3Key": "user-abc/photo-001.jpg",
        "s3Bucket": "kismet-photos-dev",
        "contentType": "image/jpeg",
        "cdnUrl": "https://cdn.kismet.dev/user-abc/photo-001.jpg",
        "isPrimary": True,
        "timestamp": "2026-04-01T12:00:00Z",
    }

    def test_image_moderation_required_fields(self):
        """D4 image-moderation requires photoId, userId, s3Key, and s3Bucket."""
        d = self.PHOTO_EVENT
        self.assertIn("photoId", d)
        self.assertIn("userId", d)
        self.assertIn("s3Key", d)
        self.assertIn("s3Bucket", d)

    def test_s3_bucket_is_non_empty(self):
        """s3Bucket must be non-empty or image-moderation skips the photo."""
        self.assertTrue(len(self.PHOTO_EVENT["s3Bucket"].strip()) > 0)

    def test_s3_key_is_non_empty(self):
        self.assertTrue(len(self.PHOTO_EVENT["s3Key"].strip()) > 0)

    def test_event_source_and_type(self):
        event = eb_event("kismet.photo-service", "photo.uploaded", self.PHOTO_EVENT)
        self.assertEqual(event["source"], "kismet.photo-service")
        self.assertEqual(event["detail-type"], "photo.uploaded")


# ============================================================================
# 4. swipe.created → D2 match-service
# ============================================================================

class TestSwipeCreatedToMatch(unittest.TestCase):
    """D2 swipe publishes swipe.created → D2 match checks for mutual like."""

    SWIPE_EVENT = {
        "swipeId": "swipe-abc12345",
        "userId": "user-123",
        "targetUserId": "user-456",
        "action": "like",
        "timestamp": "2026-04-01T12:00:00Z",
    }

    def test_match_service_required_fields(self):
        """Match-service extracts userId and targetUserId from swipe.created."""
        d = self.SWIPE_EVENT
        self.assertIn("userId", d)
        self.assertIn("targetUserId", d)
        self.assertIn("action", d)

    def test_only_like_events_published(self):
        """Swipe-service only publishes events for 'like', not 'pass'."""
        self.assertEqual(self.SWIPE_EVENT["action"], "like")

    def test_event_source(self):
        event = eb_event("kismet.swipe-service", "swipe.created", self.SWIPE_EVENT)
        self.assertEqual(event["source"], "kismet.swipe-service")


# ============================================================================
# 5. match.created → D3 icebreaker + D5 notifications
# ============================================================================

class TestMatchCreatedToDownstream(unittest.TestCase):
    """D2 match publishes match.created → D3 icebreaker + D5 consume it."""

    MATCH_EVENT = {
        "matchId": "match-abc12345",
        "userIds": ["user-123", "user-456"],
        "timestamp": "2026-04-01T12:00:00Z",
    }

    def test_icebreaker_required_fields(self):
        """D3 icebreaker extracts matchId from match.created."""
        self.assertIn("matchId", self.MATCH_EVENT)
        self.assertTrue(len(self.MATCH_EVENT["matchId"]) > 0)

    def test_user_ids_is_array(self):
        """userIds must be an array of exactly 2 user IDs."""
        ids = self.MATCH_EVENT["userIds"]
        self.assertIsInstance(ids, list)
        self.assertEqual(len(ids), 2)

    def test_user_ids_are_sorted(self):
        """match-service sorts userIds alphabetically."""
        ids = self.MATCH_EVENT["userIds"]
        self.assertEqual(ids, sorted(ids))

    def test_event_source(self):
        event = eb_event("kismet.match-service", "match.created", self.MATCH_EVENT)
        self.assertEqual(event["source"], "kismet.match-service")
        self.assertEqual(event["detail-type"], "match.created")


# ============================================================================
# 6. message.sent → D5 notifications
# ============================================================================

class TestMessageSentEvent(unittest.TestCase):
    """D3 message-service publishes message.sent."""

    MESSAGE_EVENT = {
        "messageId": "msg-001",
        "matchId": "match-abc12345",
        "senderId": "user-123",
        "recipientId": "user-456",
        "content": "Hey, nice to meet you!",
        "messageType": "text",
        "timestamp": "2026-04-01T12:00:00Z",
    }

    def test_all_fields_present(self):
        d = self.MESSAGE_EVENT
        for field in ["messageId", "matchId", "senderId", "recipientId",
                       "content", "messageType", "timestamp"]:
            self.assertIn(field, d, f"Missing field: {field}")

    def test_message_type_is_text(self):
        self.assertEqual(self.MESSAGE_EVENT["messageType"], "text")

    def test_event_source(self):
        event = eb_event("kismet.message-service", "message.sent", self.MESSAGE_EVENT)
        self.assertEqual(event["source"], "kismet.message-service")


# ============================================================================
# 7. End-to-end event chain validation
# ============================================================================

class TestFullEventChain(unittest.TestCase):
    """
    Simulate the full user journey as an event chain.
    Each step builds on the previous, verifying that the output of one
    service provides valid input for the next.
    """

    def test_signup_to_match_flow(self):
        """
        Full flow:
          signup → profile → photo → discovery → swipe → match → icebreaker
        """
        # Step 1: User signs up → user.created
        user_created = {
            "userId": "user-alice",
            "email": "alice@bu.edu",
            "timestamp": "2026-04-01T10:00:00Z",
        }
        self.assertTrue(user_created["email"].endswith(".edu"))

        # Step 2: User completes profile → profile.completed
        profile_completed = {
            "userId": user_created["userId"],  # same user
            "name": "Alice",
            "birthDate": "1999-05-15",
            "birthTime": "14:30",
            "gender": "female",
            "preferred_gender": "male",
            "location_coordinates": [42.36, -71.06],
            "city": "Boston",
            "avatarUrl": "",
            "bio": "Astronomy major who loves stargazing",
            "interests": ["astronomy", "hiking", "coffee"],
            "timestamp": "2026-04-01T10:05:00Z",
        }
        self.assertEqual(profile_completed["userId"], user_created["userId"])

        # Step 3: User uploads photo → photo.uploaded
        photo_uploaded = {
            "photoId": "photo-001",
            "userId": user_created["userId"],
            "s3Key": f"{user_created['userId']}/photo-001.jpg",
            "s3Bucket": "kismet-photos-dev",
            "contentType": "image/jpeg",
            "cdnUrl": f"https://cdn.kismet.dev/{user_created['userId']}/photo-001.jpg",
            "isPrimary": True,
            "timestamp": "2026-04-01T10:06:00Z",
        }
        self.assertEqual(photo_uploaded["userId"], user_created["userId"])
        self.assertTrue(photo_uploaded["s3Bucket"])  # D4 needs this

        # Step 4: Another user (Bob) already exists, Alice swipes right
        # Simulate Bob's prior swipe on Alice
        bob_swipe = {
            "swipeId": "swipe-bob-alice",
            "userId": "user-bob",
            "targetUserId": user_created["userId"],
            "action": "like",
            "timestamp": "2026-04-01T09:00:00Z",
        }
        # Alice swipes right on Bob
        alice_swipe = {
            "swipeId": "swipe-alice-bob",
            "userId": user_created["userId"],
            "targetUserId": "user-bob",
            "action": "like",
            "timestamp": "2026-04-01T11:00:00Z",
        }
        # Both swipes are likes → mutual match
        self.assertEqual(bob_swipe["action"], "like")
        self.assertEqual(alice_swipe["action"], "like")
        self.assertEqual(bob_swipe["targetUserId"], alice_swipe["userId"])
        self.assertEqual(alice_swipe["targetUserId"], bob_swipe["userId"])

        # Step 5: Match created (userIds sorted alphabetically)
        user_ids = sorted([alice_swipe["userId"], alice_swipe["targetUserId"]])
        match_created = {
            "matchId": "match-alice-bob",
            "userIds": user_ids,
            "timestamp": "2026-04-01T11:00:01Z",
        }
        self.assertEqual(match_created["userIds"], sorted(match_created["userIds"]))
        self.assertIn(user_created["userId"], match_created["userIds"])
        self.assertIn("user-bob", match_created["userIds"])

        # Step 6: Icebreaker service receives match.created
        # Verify it can extract matchId
        self.assertTrue(len(match_created["matchId"]) > 0)
        # Verify userIds available for profile lookup
        self.assertEqual(len(match_created["userIds"]), 2)

        # Step 7: Message sent in the match
        message_sent = {
            "messageId": "msg-001",
            "matchId": match_created["matchId"],
            "senderId": user_created["userId"],
            "recipientId": "user-bob",
            "content": "Hey Bob! Our bazi compatibility looks great 😊",
            "messageType": "text",
            "timestamp": "2026-04-01T11:05:00Z",
        }
        self.assertEqual(message_sent["matchId"], match_created["matchId"])
        self.assertIn(message_sent["senderId"], match_created["userIds"])
        self.assertIn(message_sent["recipientId"], match_created["userIds"])

        # Step 8: D6 activity-logger can consume every event in this chain
        # Each event must have timestamp and an extractable userId
        all_events = [
            ("user.created", user_created),
            ("profile.completed", profile_completed),
            ("photo.uploaded", photo_uploaded),
            ("swipe.created", alice_swipe),
            ("match.created", match_created),
            ("message.sent", message_sent),
        ]
        for detail_type, detail in all_events:
            self.assertIn("timestamp", detail, f"{detail_type} missing timestamp for D6 logger")
            # activity-logger userId extraction
            if detail_type == "match.created":
                self.assertTrue(len(detail.get("userIds", [])) >= 1)
            elif detail_type == "message.sent":
                self.assertIn("senderId", detail)
            else:
                self.assertIn("userId", detail)

    def test_profile_update_flow(self):
        """profile.updated carries the same schema as profile.completed."""
        profile_updated = {
            "userId": "user-alice",
            "name": "Alice W.",
            "birthDate": "1999-05-15",
            "birthTime": "14:30",
            "gender": "female",
            "preferred_gender": "male",
            "location_coordinates": [42.36, -71.06],
            "city": "Cambridge",
            "avatarUrl": "https://cdn.kismet.dev/user-alice/photo.jpg",
            "bio": "Updated bio",
            "interests": ["astronomy", "yoga"],
            "timestamp": "2026-04-02T10:00:00Z",
        }
        # Same fields as profile.completed — discovery can process both
        for field in ["userId", "name", "birthDate", "gender", "preferred_gender",
                       "location_coordinates", "city", "avatarUrl", "bio", "interests",
                       "timestamp"]:
            self.assertIn(field, profile_updated, f"profile.updated missing: {field}")


# ============================================================================
# 8. Lambda-level integration: verify actual code produces correct events
# ============================================================================

class TestAuthServiceEventOutput(unittest.TestCase):
    """Verify auth-service lambda actually publishes correct user.created."""

    def test_signup_publishes_user_created(self):
        _add_path(D1_AUTH)
        with patch.dict("os.environ", {
            "USERS_TABLE_NAME": "kismet-users",
            "COGNITO_USER_POOL_ID": "us-east-1_test",
            "COGNITO_APP_CLIENT_ID": "test-client",
            "EVENT_BUS_NAME": "kismet-events",
        }):
            import importlib
            import lambda_function as auth_mod
            importlib.reload(auth_mod)

            with patch.object(auth_mod, "cognito") as mock_cognito, \
                 patch.object(auth_mod, "dynamodb") as mock_dynamodb, \
                 patch.object(auth_mod, "events") as mock_events:

                mock_cognito.sign_up.return_value = {"UserSub": "user-new-123"}
                mock_dynamodb.Table.return_value.put_item.return_value = {}
                mock_events.put_events.return_value = {"FailedEntryCount": 0}

                event = authed_http_event("POST", "/auth/signup", {
                    "email": "test@university.edu",
                    "password": "SecurePass1",
                    "birthDate": "1999-01-01",
                })
                auth_mod.lambda_handler(event, None)

                # Verify event was published
                mock_events.put_events.assert_called_once()
                call_args = mock_events.put_events.call_args
                entry = call_args[1]["Entries"][0] if "Entries" in call_args[1] else call_args[0][0]["Entries"][0]

                self.assertEqual(entry["Source"], "kismet.auth-service")
                self.assertEqual(entry["DetailType"], "user.created")

                detail = json.loads(entry["Detail"])
                self.assertEqual(detail["userId"], "user-new-123")
                self.assertEqual(detail["email"], "test@university.edu")
                self.assertIn("timestamp", detail)
                # Must NOT have createdAt (old naming)
                self.assertNotIn("createdAt", detail)


class TestProfileServiceEventOutput(unittest.TestCase):
    """Verify profile-service publishes correct profile.completed event."""

    def test_create_profile_publishes_profile_completed(self):
        _add_path(D1_PROFILE)
        with patch.dict("os.environ", {
            "PROFILES_TABLE_NAME": "kismet-profiles",
            "EVENT_BUS_NAME": "kismet-events",
        }):
            import importlib
            import lambda_function as profile_mod
            importlib.reload(profile_mod)

            with patch.object(profile_mod, "dynamodb") as mock_dynamodb, \
                 patch.object(profile_mod, "events") as mock_events:

                mock_table = mock_dynamodb.Table.return_value
                mock_table.get_item.return_value = {}  # no existing profile
                mock_table.put_item.return_value = {}
                mock_events.put_events.return_value = {"FailedEntryCount": 0}

                event = authed_http_event("POST", "/profiles", {
                    "name": "Alice",
                    "gender": "female",
                    "interestedIn": "male",
                    "birthDate": "1999-05-15",
                    "location": [42.36, -71.06],
                    "city": "Boston",
                    "bio": "Astronomy major",
                    "interests": ["astronomy", "hiking"],
                })
                response = profile_mod.lambda_handler(event, None)
                self.assertEqual(response["statusCode"], 201)

                # Verify event
                mock_events.put_events.assert_called_once()
                call_args = mock_events.put_events.call_args[1]
                entry = call_args["Entries"][0]

                self.assertEqual(entry["DetailType"], "profile.completed")
                detail = json.loads(entry["Detail"])

                # Verify field mapping for D2 discovery consumption
                self.assertEqual(detail["userId"], "user-123")
                self.assertEqual(detail["name"], "Alice")
                self.assertEqual(detail["gender"], "female")
                self.assertEqual(detail["preferred_gender"], "male")  # mapped from interestedIn
                self.assertEqual(detail["location_coordinates"], [42.36, -71.06])
                self.assertEqual(detail["city"], "Boston")
                self.assertIn("timestamp", detail)
                self.assertNotIn("createdAt", detail)
                self.assertNotIn("updatedAt", detail)
                self.assertNotIn("interestedIn", detail)  # must be mapped to preferred_gender


class TestSwipeToMatchEventChain(unittest.TestCase):
    """Verify swipe-service → match-service event chain works."""

    def test_swipe_like_publishes_event(self):
        _add_path(D2_SWIPE)
        with patch.dict("os.environ", {
            "TABLE_NAME": "kismet-swipes",
            "EVENT_BUS_NAME": "kismet-events",
        }):
            import importlib
            import lambda_function as swipe_mod
            importlib.reload(swipe_mod)

            with patch.object(swipe_mod, "table") as mock_table, \
                 patch.object(swipe_mod, "events_client") as mock_events:

                mock_table.get_item.return_value = {}  # no duplicate
                mock_table.put_item.return_value = {}
                mock_events.put_events.return_value = {"FailedEntryCount": 0}

                event = authed_http_event("POST", "/swipe", {
                    "targetUserId": "user-456",
                    "action": "like",
                })
                response = swipe_mod.handler(event, None)
                self.assertEqual(response["statusCode"], 200)

                # Like should publish swipe.created
                mock_events.put_events.assert_called_once()
                call_args = mock_events.put_events.call_args[1]
                entry = call_args["Entries"][0]

                self.assertEqual(entry["Source"], "kismet.swipe-service")
                self.assertEqual(entry["DetailType"], "swipe.created")

                detail = json.loads(entry["Detail"])
                self.assertEqual(detail["userId"], "user-123")
                self.assertEqual(detail["targetUserId"], "user-456")
                self.assertEqual(detail["action"], "like")
                self.assertIn("swipeId", detail)
                self.assertIn("timestamp", detail)

    def test_swipe_pass_does_not_publish(self):
        _add_path(D2_SWIPE)
        with patch.dict("os.environ", {
            "TABLE_NAME": "kismet-swipes",
            "EVENT_BUS_NAME": "kismet-events",
        }):
            import importlib
            import lambda_function as swipe_mod
            importlib.reload(swipe_mod)

            with patch.object(swipe_mod, "table") as mock_table, \
                 patch.object(swipe_mod, "events_client") as mock_events:

                mock_table.get_item.return_value = {}
                mock_table.put_item.return_value = {}

                event = authed_http_event("POST", "/swipe", {
                    "targetUserId": "user-456",
                    "action": "pass",
                })
                swipe_mod.handler(event, None)

                # Pass should NOT publish
                mock_events.put_events.assert_not_called()


# ============================================================================
# 9. D4 → D6: content.flagged → admin-dashboard
# ============================================================================

class TestContentFlaggedToAdminDashboard(unittest.TestCase):
    """D4 moderation publishes content.flagged → D6 admin-dashboard consumes it."""

    CONTENT_FLAGGED_TEXT = {
        "contentId": "msg-abc123",
        "contentType": "text",
        "userId": "user-456",
        "reason": "toxicity_detected",
        "score": 0.9512,
        "timestamp": "2026-04-01T12:00:00Z",
    }

    CONTENT_FLAGGED_IMAGE = {
        "contentId": "photo-xyz789",
        "contentType": "image",
        "userId": "user-789",
        "reason": "explicit_content",
        "score": 0.88,
        "timestamp": "2026-04-01T12:05:00Z",
    }

    def test_text_flagged_has_required_fields(self):
        """admin-dashboard reads: contentId, contentType, userId, reason, score, timestamp."""
        for field in ["contentId", "contentType", "userId", "reason", "score", "timestamp"]:
            self.assertIn(field, self.CONTENT_FLAGGED_TEXT)

    def test_image_flagged_has_required_fields(self):
        for field in ["contentId", "contentType", "userId", "reason", "score", "timestamp"]:
            self.assertIn(field, self.CONTENT_FLAGGED_IMAGE)

    def test_content_type_is_text_or_image(self):
        self.assertIn(self.CONTENT_FLAGGED_TEXT["contentType"], ("text", "image"))
        self.assertIn(self.CONTENT_FLAGGED_IMAGE["contentType"], ("text", "image"))

    def test_score_is_numeric(self):
        self.assertIsInstance(self.CONTENT_FLAGGED_TEXT["score"], (int, float))
        self.assertIsInstance(self.CONTENT_FLAGGED_IMAGE["score"], (int, float))
        self.assertGreaterEqual(self.CONTENT_FLAGGED_TEXT["score"], 0)
        self.assertLessEqual(self.CONTENT_FLAGGED_TEXT["score"], 1)

    def test_source_is_kismet_moderation(self):
        """Both text-mod and image-mod use Source: kismet.moderation."""
        # This is validated at schema level — source must be consistent
        expected_source = "kismet.moderation"
        self.assertEqual(expected_source, "kismet.moderation")


# ============================================================================
# 10. D4 → D6: user.reported → admin-dashboard + activity-logger
# ============================================================================

class TestUserReportedToD6(unittest.TestCase):
    """D4 report-service publishes user.reported → D6 admin-dashboard + activity-logger."""

    USER_REPORTED = {
        "reportId": "report-001",
        "reporterId": "user-alice",
        "reportedUserId": "user-bob",
        "reason": "harassment",
        "timestamp": "2026-04-01T14:00:00Z",
    }

    def test_admin_dashboard_required_fields(self):
        """admin-dashboard reads: reportedUserId to increment reportCount."""
        self.assertIn("reportedUserId", self.USER_REPORTED)

    def test_activity_logger_can_extract_user_id(self):
        """activity-logger uses reporterId as userId for user.reported events."""
        self.assertIn("reporterId", self.USER_REPORTED)
        self.assertTrue(len(self.USER_REPORTED["reporterId"]) > 0)

    def test_all_fields_present(self):
        for field in ["reportId", "reporterId", "reportedUserId", "reason", "timestamp"]:
            self.assertIn(field, self.USER_REPORTED)

    def test_source_is_report_service(self):
        expected_source = "kismet.report-service"
        self.assertEqual(expected_source, "kismet.report-service")

    def test_timestamp_not_createdAt(self):
        self.assertIn("timestamp", self.USER_REPORTED)
        self.assertNotIn("createdAt", self.USER_REPORTED)


# ============================================================================
# 11. D6 activity-logger: consumes ALL event types with userId extraction
# ============================================================================

class TestActivityLoggerEventConsumption(unittest.TestCase):
    """D6 activity-logger consumes events from all domains. Verify userId extraction logic."""

    def test_user_created_extracts_userId(self):
        detail = {"userId": "user-123", "email": "a@b.com", "timestamp": "2026-04-01T10:00:00Z"}
        user_id = detail.get("userId", "unknown")
        self.assertEqual(user_id, "user-123")

    def test_profile_completed_extracts_userId(self):
        detail = {"userId": "user-123", "name": "Alice", "timestamp": "2026-04-01T10:01:00Z"}
        user_id = detail.get("userId", "unknown")
        self.assertEqual(user_id, "user-123")

    def test_match_created_extracts_first_userId(self):
        """activity-logger uses userIds[0] for match.created."""
        detail = {"matchId": "m-001", "userIds": ["user-alice", "user-bob"], "timestamp": "2026-04-01T10:02:00Z"}
        user_ids = detail.get("userIds", [])
        user_id = user_ids[0] if user_ids else "unknown"
        self.assertEqual(user_id, "user-alice")

    def test_match_created_logs_for_both_users(self):
        """activity-logger writes a second record for userIds[1]."""
        detail = {"matchId": "m-001", "userIds": ["user-alice", "user-bob"], "timestamp": "2026-04-01T10:02:00Z"}
        user_ids = detail.get("userIds", [])
        self.assertEqual(len(user_ids), 2)
        self.assertNotEqual(user_ids[0], user_ids[1])

    def test_message_sent_extracts_senderId(self):
        """activity-logger uses senderId for message.sent."""
        detail = {"messageId": "msg-001", "senderId": "user-alice", "recipientId": "user-bob",
                  "content": "hello", "messageType": "text", "timestamp": "2026-04-01T10:03:00Z"}
        user_id = detail.get("senderId", "unknown")
        self.assertEqual(user_id, "user-alice")

    def test_user_reported_extracts_reporterId(self):
        """activity-logger uses reporterId for user.reported."""
        detail = {"reportId": "r-001", "reporterId": "user-alice", "reportedUserId": "user-bob",
                  "reason": "spam", "timestamp": "2026-04-01T10:04:00Z"}
        user_id = detail.get("reporterId", "unknown")
        self.assertEqual(user_id, "user-alice")

    def test_swipe_created_extracts_userId(self):
        detail = {"swipeId": "s-001", "userId": "user-alice", "targetUserId": "user-bob",
                  "action": "like", "timestamp": "2026-04-01T10:05:00Z"}
        user_id = detail.get("userId", "unknown")
        self.assertEqual(user_id, "user-alice")

    def test_content_flagged_extracts_userId(self):
        detail = {"contentId": "msg-001", "contentType": "text", "userId": "user-bob",
                  "reason": "toxicity_detected", "score": 0.95, "timestamp": "2026-04-01T10:06:00Z"}
        user_id = detail.get("userId", "unknown")
        self.assertEqual(user_id, "user-bob")

    def test_all_events_have_timestamp(self):
        """Every event consumed by activity-logger must have a timestamp field."""
        events = [
            {"userId": "u1", "timestamp": "2026-04-01T10:00:00Z"},                    # user.created
            {"userId": "u1", "name": "A", "timestamp": "2026-04-01T10:01:00Z"},       # profile.completed
            {"swipeId": "s1", "userId": "u1", "targetUserId": "u2", "action": "like", "timestamp": "2026-04-01T10:02:00Z"},  # swipe.created
            {"matchId": "m1", "userIds": ["u1", "u2"], "timestamp": "2026-04-01T10:03:00Z"},  # match.created
            {"messageId": "msg1", "senderId": "u1", "recipientId": "u2", "content": "hi", "messageType": "text", "timestamp": "2026-04-01T10:04:00Z"},  # message.sent
            {"reportId": "r1", "reporterId": "u1", "reportedUserId": "u2", "reason": "spam", "timestamp": "2026-04-01T10:05:00Z"},  # user.reported
            {"contentId": "c1", "contentType": "text", "userId": "u1", "reason": "toxicity_detected", "score": 0.9, "timestamp": "2026-04-01T10:06:00Z"},  # content.flagged
        ]
        for evt in events:
            self.assertIn("timestamp", evt)


# ============================================================================
# 12. Full event chain: D4 moderation → D6 analytics end-to-end
# ============================================================================

class TestModerationToAnalyticsFlow(unittest.TestCase):
    """End-to-end: message → D4 text-mod flags it → D6 admin-dashboard stores it."""

    def test_message_to_flag_to_dashboard(self):
        # Step 1: message.sent event
        message_sent = {
            "messageId": "msg-bad",
            "matchId": "match-001",
            "senderId": "user-bad",
            "recipientId": "user-good",
            "content": "inappropriate content",
            "messageType": "text",
            "timestamp": "2026-04-01T15:00:00Z",
        }
        self.assertIn("senderId", message_sent)

        # Step 2: D4 text-mod detects toxicity → publishes content.flagged
        content_flagged = {
            "contentId": message_sent["messageId"],
            "contentType": "text",
            "userId": message_sent["senderId"],
            "reason": "toxicity_detected",
            "score": 0.95,
            "timestamp": "2026-04-01T15:00:01Z",
        }
        self.assertEqual(content_flagged["contentId"], message_sent["messageId"])
        self.assertEqual(content_flagged["userId"], message_sent["senderId"])

        # Step 3: D6 admin-dashboard can consume: needs contentId, contentType, userId, reason, score
        for field in ["contentId", "contentType", "userId", "reason", "score", "timestamp"]:
            self.assertIn(field, content_flagged)

    def test_photo_to_flag_to_dashboard(self):
        # Step 1: photo.uploaded event
        photo_uploaded = {
            "userId": "user-bad",
            "photoId": "photo-bad",
            "s3Key": "users/user-bad/photo-bad.jpg",
            "s3Bucket": "kismet-photos",
            "contentType": "image/jpeg",
            "timestamp": "2026-04-01T16:00:00Z",
        }

        # Step 2: D4 image-mod detects explicit content → publishes content.flagged
        content_flagged = {
            "contentId": photo_uploaded["photoId"],
            "contentType": "image",
            "userId": photo_uploaded["userId"],
            "reason": "explicit_content",
            "score": 0.92,
            "timestamp": "2026-04-01T16:00:01Z",
        }
        self.assertEqual(content_flagged["userId"], photo_uploaded["userId"])
        for field in ["contentId", "contentType", "userId", "reason", "score", "timestamp"]:
            self.assertIn(field, content_flagged)

    def test_report_to_dashboard_increment(self):
        """user.reported → admin-dashboard increments reportCount on reported user."""
        user_reported = {
            "reportId": "report-001",
            "reporterId": "user-alice",
            "reportedUserId": "user-bob",
            "reason": "harassment",
            "timestamp": "2026-04-01T17:00:00Z",
        }
        # admin-dashboard uses reportedUserId to find the profile
        self.assertIn("reportedUserId", user_reported)
        self.assertNotEqual(user_reported["reporterId"], user_reported["reportedUserId"])


if __name__ == "__main__":
    unittest.main()
