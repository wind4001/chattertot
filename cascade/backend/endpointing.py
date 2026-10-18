"""Bounded, packet-independent PCM endpointing without cloud calls or audio retention.

Energy gating adapts to observed quiet background, not speaker identity. Television
speech and abrupt loud continuous noise still require real-world evaluation.
"""
import array
from collections import deque
from dataclasses import dataclass, field


FRAME_MS = 20
FRAME_BYTES = 640  # 16 kHz, mono signed int16
END_SILENCE_MS = 1400
MAX_TURN_MS = 20000
ATTACK_MS = 80


@dataclass(frozen=True)
class EndpointEvent:
    kind: str
    pcm: bytes = field(default=b'', repr=False)
    reason: str = ''
    silence_ms: int = 0
    threshold: int = 0


def rms(pcm):
    samples = array.array('h')
    samples.frombytes(pcm)
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


class EndpointDetector:
    def __init__(self):
        self.pending = bytearray()
        self.noise = 80.0
        self.preroll = deque(maxlen=15)  # 300 ms includes onset confirmation
        self.idle_audio_ms = 0
        self.reset()

    @property
    def threshold(self):
        return round(max(300, min(1800, self.noise * 2.5)))

    def reset(self):
        """Discard a cancelled candidate, retaining the room's quiet baseline."""
        self.pending.clear()
        self.preroll.clear()
        self.speaking = False
        self.audio = bytearray()
        self.silence_ms = 0
        self.attack_ms = 0

    def feed(self, pcm):
        self.pending.extend(pcm)
        events = []
        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            energy = rms(frame)
            voiced = energy > self.threshold
            self.attack_ms = self.attack_ms + FRAME_MS if voiced else 0
            if not self.speaking:
                self.preroll.append(frame)
                # Adapt only outside confirmed speech, never learn the child's voice
                # or AI playback as a rising threshold during an active utterance.
                if not voiced:
                    self.noise += 0.08 * (energy - self.noise)
                if self.attack_ms < ATTACK_MS:
                    self.idle_audio_ms += FRAME_MS
                    continue
                self.speaking = True
                self.audio.extend(b''.join(self.preroll))
                self.preroll.clear()
                self.silence_ms = 0
                events.append(EndpointEvent('start'))
                continue

            self.audio.extend(frame)
            # A single click neither starts a turn nor postpones an endpoint.
            self.silence_ms = 0 if self.attack_ms >= ATTACK_MS else self.silence_ms + FRAME_MS
            reason = ('max_duration' if len(self.audio) >= MAX_TURN_MS * 32 else
                      'silence' if self.silence_ms >= END_SILENCE_MS and not voiced else '')
            if reason:
                # Send only 200ms trailing quiet to ASR/speaker/KWS. The endpoint
                # wait is latency, not extra voiced material for speaker enrollment.
                trim = max(0, self.silence_ms - 200) * 32
                audio = bytes(self.audio[:-trim] if trim else self.audio)
                events.append(EndpointEvent('end', audio, reason,
                                            self.silence_ms, self.threshold))
                self.speaking = False
                self.audio.clear()
                self.attack_ms = 0
                self.silence_ms = 0
        return events
