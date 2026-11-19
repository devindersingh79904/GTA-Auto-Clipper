import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import audio_mix
from clip import audio_args
from llm_metadata import finalize


class MusicTrackTests(unittest.TestCase):
    def test_tracks_are_listed_and_sidecar_credit_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.mp3", "a.wav", "notes.txt", "a.txt"):
                Path(d, name).write_text("Song by Artist" if name == "a.txt" else "x", encoding="utf-8")
            tracks = audio_mix.music_tracks(d)
            self.assertEqual([os.path.basename(t) for t in tracks], ["a.wav", "b.mp3"])
            self.assertEqual(audio_mix.music_credit(tracks[0]), "Song by Artist")
            self.assertIsNone(audio_mix.music_credit(tracks[1]))

    def test_missing_folder_has_no_tracks(self):
        self.assertEqual(audio_mix.music_tracks(os.path.join(tempfile.gettempdir(), "no-such-music-dir")), [])


class FilterTests(unittest.TestCase):
    def test_music_mode_replaces_source_audio(self):
        inputs, graph = audio_args("music", 30, ("track.mp3", 12.5))
        self.assertEqual(inputs, ["-stream_loop", "-1", "-ss", "12.50", "-i", "track.mp3"])
        self.assertTrue(graph.startswith("[1:a]") and graph.endswith("[aout]"))
        self.assertNotIn("[0:a]", graph)

    def test_mute_mode_uses_silence(self):
        inputs, graph = audio_args("mute", 30)
        self.assertIn("anullsrc=r=48000:cl=stereo", inputs)
        self.assertNotIn("afade", graph)

    def test_original_mode_keeps_stream_audio(self):
        self.assertEqual(audio_args("original", 30), ([], "[0:a]asetpts=PTS-STARTPTS[aout]"))

    def test_voice_and_music_are_mixed(self):
        graph = audio_mix.mix_filter(30, "1:a", "2:a", None, music_volume=0.15)
        self.assertIn("amix=inputs=2", graph)
        self.assertTrue(graph.endswith("[aout]"))

    def test_single_source_needs_no_amix(self):
        graph = audio_mix.mix_filter(30, "1:a", None)
        self.assertNotIn("amix", graph)
        self.assertTrue(graph.endswith("[aout]"))


class MetadataTests(unittest.TestCase):
    def test_music_credit_goes_in_description(self):
        _, desc, _ = finalize({"title": "t", "description": "d", "hashtags": []}, {"music_credit": "Song by Artist"})
        self.assertIn("Music: Song by Artist", desc)


if __name__ == "__main__":
    unittest.main()
