"""Exercise fake provider HTTP responses against the current analysis contracts."""

from __future__ import annotations

from email.message import EmailMessage
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend") if (ROOT / "backend").exists() else "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from app.schemas.ai_creator_map_reduce import (  # noqa: E402
    CreatorBriefSynthesis,
    CreatorCommercialSafetyReduction,
    CreatorContentFormatReduction,
    CreatorPerformanceAudienceReduction,
    CreatorPresentationReduction,
    CreatorVideoBatchDigest,
)
from app.integrations.deepseek import DeepSeekGateway  # noqa: E402
from app.integrations.errors import PermanentIntegrationError  # noqa: E402
from app.outreach.smtp import SMTPConfig, SMTPTransientError  # noqa: E402
from app.schemas.ai_creator import CreatorVisualAnalysis  # noqa: E402
from app.schemas.ai_game import GameVisualAnalysis  # noqa: E402
from capture_smtp import capture_gateway  # noqa: E402
from fake_images import FakeImageLoader, INLINE_IMAGE, image_gateway  # noqa: E402


class FakeImageTests(unittest.TestCase):
    def test_known_fixture_is_inline_without_any_network(self) -> None:
        with patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS")):
            self.assertEqual(
                FakeImageLoader().load(
                    "https://images.integration.invalid/steam/1245620.png"
                ),
                INLINE_IMAGE,
            )

    def test_unexpected_source_is_not_downloaded(self) -> None:
        with patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS")):
            with self.assertRaises(PermanentIntegrationError):
                FakeImageLoader().load(
                    "https://i.ytimg.com/vi/real-video/hqdefault.jpg"
                )


class CaptureSMTPTests(unittest.TestCase):
    def test_gateway_captures_message_without_network(self) -> None:
        config = SMTPConfig(
            host="smtp.integration.invalid",
            port=465,
            encryption="tls",
            username="sender@example.com",
            password="synthetic-smtp-integration-key",
            from_name="Integration Team",
            reply_to="reply@example.com",
        )
        message = EmailMessage()
        message["To"] = "creator@example.com"
        message["From"] = "sender@example.com"
        message.set_content("Synthetic integration invitation.")
        with tempfile.TemporaryDirectory() as state, patch.dict(
            os.environ, {"FAKE_STATE_DIR": state}
        ):
            with patch(
                "socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS")
            ), patch(
                "socket.create_connection",
                side_effect=AssertionError("Unexpected SMTP socket"),
            ):
                receipt = capture_gateway().send(config, message)
            self.assertEqual(receipt.accepted_recipients, 1)
            captured = list(Path(state).glob("smtp-*.eml"))
            self.assertEqual(len(captured), 1)
            self.assertIn("Synthetic integration invitation.", captured[0].read_text())

    def test_gateway_rejects_unexpected_destination(self) -> None:
        config = SMTPConfig(
            host="smtp.example.com",
            port=465,
            encryption="tls",
            username="sender@example.com",
            password="synthetic-smtp-integration-key",
            from_name="Integration Team",
            reply_to="reply@example.com",
        )
        with patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS")):
            with self.assertRaises(SMTPTransientError):
                capture_gateway().probe(config)


class FakeCreatorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = tempfile.TemporaryDirectory(prefix="fmg-fake-contract-")
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "runtime/fake_external.py"),
            ],
            env={**os.environ, "FAKE_STATE_DIR": cls.state.name},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                urlopen("http://127.0.0.1:18081/ready", timeout=0.2)
            except HTTPError:
                return
            except URLError:
                time.sleep(0.05)
        cls.tearDownClass()
        raise AssertionError("fake provider did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        cls.process.communicate(timeout=5)
        cls.state.cleanup()

    def assert_schema_response(self, schema) -> None:
        with DeepSeekGateway(
            api_key="synthetic-contract-key", base_url="http://127.0.0.1:18081/deepseek"
        ) as gateway:
            parsed = gateway.complete_structured("deepseek-test", [], schema)
        self.assertTrue(parsed.english_language_check)

    def test_video_batch(self) -> None:
        self.assert_schema_response(CreatorVideoBatchDigest)

    def test_content_format(self) -> None:
        self.assert_schema_response(CreatorContentFormatReduction)

    def test_presentation(self) -> None:
        self.assert_schema_response(CreatorPresentationReduction)

    def test_performance_audience(self) -> None:
        self.assert_schema_response(CreatorPerformanceAudienceReduction)

    def test_commercial_safety(self) -> None:
        self.assert_schema_response(CreatorCommercialSafetyReduction)

    def test_creator_brief(self) -> None:
        self.assert_schema_response(CreatorBriefSynthesis)

    def assert_vision_response(self, schema, *, image_url: str, reference: str) -> None:
        with image_gateway(
            api_key="synthetic-contract-key", base_url="http://127.0.0.1:18081/deepseek"
        ) as gateway:
            parsed = gateway.complete_vision(
                "deepseek-vision-test",
                '{"asset_ref":"' + reference + '"}',
                [image_url],
                schema,
            )
        self.assertEqual(parsed.status, "available")
        self.assertEqual(parsed.visual_style.evidence[0].reference, reference)

    def test_game_vision_transmits_inline_image(self) -> None:
        self.assert_vision_response(
            GameVisualAnalysis,
            image_url="https://images.integration.invalid/steam/1245620.png",
            reference="header:0",
        )

    def test_creator_vision_transmits_inline_image(self) -> None:
        self.assert_vision_response(
            CreatorVisualAnalysis,
            image_url="https://images.integration.invalid/youtube/video-recovery01.png",
            reference="video:video-recovery01:thumbnail:0",
        )

    def test_fake_provider_rejects_remote_image_urls(self) -> None:
        with DeepSeekGateway(
            api_key="synthetic-contract-key", base_url="http://127.0.0.1:18081/deepseek"
        ) as gateway:
            with self.assertRaises(PermanentIntegrationError):
                gateway._complete(
                    "deepseek-vision-test",
                    [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": '{"asset_ref":"header:0"}'},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "https://images.integration.invalid/steam/1245620.png"
                                    },
                                },
                            ],
                        }
                    ],
                    GameVisualAnalysis,
                    max_tokens=None,
                )


if __name__ == "__main__":
    unittest.main()
