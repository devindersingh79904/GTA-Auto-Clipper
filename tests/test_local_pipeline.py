import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from clip import video_encoder_args
from llm_metadata import finalize
from youtube_upload import check_metadata, check_short, ensure_shorts_tag, request_body


class ConfigTests(unittest.TestCase):
    def test_env_file_parses_comments_quotes_and_keeps_real_env(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# comment\nA=1   # trailing\nB=\"x # y\"\nC=from-file\n\nnot a line\n")
            env = {"C": "from-env"}
            config.load_env_file(path, env)
        self.assertEqual(env, {"A": "1", "B": "x # y", "C": "from-env"})


class EncoderTests(unittest.TestCase):
    def test_nvenc_uses_constant_quality(self):
        args = video_encoder_args("h264_nvenc")
        self.assertEqual(args[:2], ["-c:v", "h264_nvenc"])
        self.assertIn("-cq", args)

    def test_libx264_keeps_original_settings(self):
        self.assertEqual(video_encoder_args("libx264"), ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"])


class MetadataTests(unittest.TestCase):
    def test_shorts_tag_added_and_hashtags_cleaned(self):
        title, desc, tags = finalize({"title": "Huge crash #wow", "description": "A chase ends badly.",
                                      "hashtags": ["GTA 6", "#gta6", "#Crash"]}, {})
        self.assertEqual(title, "Huge crash")
        self.assertEqual(tags[0], "#Shorts")
        self.assertIn("#GTA6", tags)
        self.assertEqual(len([t for t in tags if t.lower() == "#gta6"]), 1)
        self.assertIn("#Shorts", desc)

    def test_stray_chinese_words_are_removed(self):
        _, desc, _ = finalize({"title": "t", "description": "A惊险 moment", "hashtags": []}, {})
        self.assertTrue(desc.startswith("A moment"))

    def test_credit_is_kept_in_description(self):
        _, desc, _ = finalize({"title": "t", "description": "d", "hashtags": []},
                              {"credit": "Streamer", "source_url": "https://youtube.com/watch?v=x"})
        self.assertIn("Credit: Streamer (https://youtube.com/watch?v=x)", desc)


class UploadChecks(unittest.TestCase):
    def test_vertical_short_passes(self):
        self.assertEqual(check_short(1080, 1920, 30.0, 59), [])

    def test_landscape_or_long_video_fails(self):
        self.assertTrue(check_short(1920, 1080, 30.0, 59))
        self.assertTrue(check_short(1080, 1920, 61.0, 59))

    def test_test_clips_and_missing_titles_are_refused(self):
        self.assertTrue(check_metadata({"test": True, "title": "t", "youtube_description": "d"}, "private"))
        self.assertTrue(check_metadata({"title": None, "youtube_description": None}, "private"))

    def test_private_upload_needs_no_approval_but_public_does(self):
        meta = {"title": "t", "youtube_description": "d"}
        self.assertEqual(check_metadata(meta, "private"), [])
        self.assertTrue(check_metadata(meta, "public"))
        self.assertEqual(check_metadata({**meta, "approved": True}, "public"), [])

    def test_already_uploaded_clip_is_refused(self):
        self.assertTrue(check_metadata({"title": "t", "youtube_description": "d", "youtube_video_id": "abc"}, "private"))

    def test_request_body_has_shorts_tag_and_privacy(self):
        body = request_body({"title": "t", "youtube_description": "d", "hashtags": ["#GTA6"]}, "private")
        self.assertIn("#Shorts", body["snippet"]["description"])
        self.assertEqual(body["snippet"]["tags"], ["GTA6"])
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(ensure_shorts_tag("x #shorts"), "x #shorts")


if __name__ == "__main__":
    unittest.main()
