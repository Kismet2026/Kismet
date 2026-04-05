import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

# So `import lambda_function` works when running tests from repo / CI
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lambda_function import handle_eventbridge, lambda_handler


def _ctx(rid="req-test"):
    return SimpleNamespace(aws_request_id=rid)


class TestHttpScaffold(unittest.TestCase):
    def test_post_moderate_returns_501_with_operation(self):
        event = {
            "httpMethod": "POST",
            "path": "/moderate/text",
            "body": json.dumps(
                {
                    "content": "hello",
                    "contentId": "msg-1",
                    "contentType": "message",
                }
            ),
        }
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 501)
        body = json.loads(resp["body"])
        self.assertEqual(body["error"]["code"], "NOT_IMPLEMENTED")
        self.assertEqual(body["operation"], "moderateText")
        self.assertEqual(body["receivedBodyKeys"], ["content", "contentId", "contentType"])

    def test_post_invalid_json_sets_body_parse_note(self):
        event = {
            "httpMethod": "POST",
            "path": "/moderate/text",
            "body": '{"broken":',
        }
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 501)
        body = json.loads(resp["body"])
        self.assertIn("bodyParseNote", body)

    def test_get_history_returns_501(self):
        event = {
            "httpMethod": "GET",
            "path": "/moderate/text/history",
            "queryStringParameters": {"limit": "20"},
        }
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 501)
        body = json.loads(resp["body"])
        self.assertEqual(body["operation"], "moderateTextHistory")
        self.assertEqual(body["queryKeys"], ["limit"])

    def test_unknown_subpath_under_moderate_text_is_404(self):
        event = {"httpMethod": "GET", "path": "/moderate/text/foo"}
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 404)
        body = json.loads(resp["body"])
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

    def test_http_api_style_event(self):
        event = {
            "requestContext": {
                "http": {"method": "POST", "path": "/moderate/text"},
            },
            "body": "{}",
        }
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 501)


class TestEventBridgeStub(unittest.TestCase):
    def test_lambda_routes_to_eventbridge_handler(self):
        event = {
            "source": "kismet.message-service",
            "detail-type": "message.sent",
            "detail": {"messageId": "m1", "content": "hi"},
        }
        resp = lambda_handler(event, _ctx())
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["error"]["code"], "NOT_IMPLEMENTED")
        self.assertEqual(body["source"], "kismet.message-service")

    def test_handle_eventbridge_direct(self):
        event = {
            "source": "x",
            "detail-type": "y",
            "detail": {},
        }
        resp = handle_eventbridge(event, _ctx("r2"))
        body = json.loads(resp["body"])
        self.assertEqual(body["requestId"], "r2")


if __name__ == "__main__":
    unittest.main()
