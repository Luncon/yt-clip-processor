"""Waveform input for faster-whisper."""

import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yt_clip_processor.transcription import _read_pcm16_mono


class TranscriptionInputTests(unittest.TestCase):
    def test_pcm16_wave_is_normalized_for_whisper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunk.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(struct.pack("<5h", -32768, -16384, 0, 16384, 32767))

            samples = _read_pcm16_mono(path)
            self.assertEqual(str(samples.dtype), "float32")
            self.assertEqual(len(samples), 5)
            self.assertAlmostEqual(samples[0], -1.0)
            self.assertAlmostEqual(samples[1], -0.5)
            self.assertAlmostEqual(samples[2], 0.0)
            self.assertAlmostEqual(samples[3], 0.5)
            self.assertGreater(samples[4], 0.99)


if __name__ == "__main__":
    unittest.main()
