import asyncio
import importlib.util
import io
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import UserProfile, VoiceProfile, utcnow


class LocalVoiceUnavailableError(RuntimeError):
    pass


@dataclass
class SpeakerMatch:
    username: str | None
    similarity: float
    accepted: bool


def local_voice_dependencies() -> dict[str, bool]:
    return {
        "faster_whisper": importlib.util.find_spec("faster_whisper") is not None,
        "speechbrain": importlib.util.find_spec("speechbrain") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
    }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return numerator / (left_norm * right_norm)


def normalize_embedding(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise LocalVoiceUnavailableError("empty_speaker_embedding")
    return [value / norm for value in values]


class LocalVoiceEngine:
    """Lazy local inference engine.

    Models are downloaded once on first use and cached in the persistent ali_data
    volume. No audio is retained after a request; only voice embeddings are saved.
    """

    _whisper_models: dict[tuple[str, str, str], Any] = {}
    _speaker_models: dict[str, Any] = {}
    _model_lock = threading.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings
        Path(settings.ali_voice_model_cache).mkdir(parents=True, exist_ok=True)

    def _whisper(self):
        deps = local_voice_dependencies()
        if not deps["faster_whisper"]:
            raise LocalVoiceUnavailableError("faster_whisper_not_installed")
        key = (
            self.settings.ali_local_stt_model,
            self.settings.ali_local_stt_device,
            self.settings.ali_local_stt_compute_type,
        )
        with self._model_lock:
            if key not in self._whisper_models:
                from faster_whisper import WhisperModel

                self._whisper_models[key] = WhisperModel(
                    self.settings.ali_local_stt_model,
                    device=self.settings.ali_local_stt_device,
                    compute_type=self.settings.ali_local_stt_compute_type,
                    download_root=str(Path(self.settings.ali_voice_model_cache) / "whisper"),
                )
        return self._whisper_models[key]

    def _speaker_encoder(self):
        deps = local_voice_dependencies()
        if not deps["speechbrain"] or not deps["torch"]:
            raise LocalVoiceUnavailableError("speaker_dependencies_not_installed")
        source = self.settings.ali_speaker_model
        with self._model_lock:
            if source not in self._speaker_models:
                from speechbrain.inference.classifiers import EncoderClassifier

                savedir = Path(self.settings.ali_voice_model_cache) / "speaker-ecapa"
                self._speaker_models[source] = EncoderClassifier.from_hparams(
                    source=source,
                    savedir=str(savedir),
                    run_opts={"device": "cpu"},
                )
        return self._speaker_models[source]

    def transcribe(self, audio_bytes: bytes) -> str:
        if not self.settings.ali_local_stt_enabled:
            raise LocalVoiceUnavailableError("local_stt_disabled")
        model = self._whisper()
        segments, _ = model.transcribe(
            io.BytesIO(audio_bytes),
            language=self.settings.ali_language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        if not text:
            raise LocalVoiceUnavailableError("empty_local_transcription")
        return text

    def speaker_embedding(self, audio_bytes: bytes) -> list[float]:
        if not self.settings.ali_speaker_id_enabled:
            raise LocalVoiceUnavailableError("speaker_id_disabled")
        deps = local_voice_dependencies()
        if not deps["faster_whisper"]:
            raise LocalVoiceUnavailableError("faster_whisper_not_installed")

        from faster_whisper.audio import decode_audio
        import torch

        audio = decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
        if audio is None or len(audio) < 8000:
            raise LocalVoiceUnavailableError("speaker_sample_too_short")
        waveform = torch.tensor(audio, dtype=torch.float32).unsqueeze(0)
        with torch.inference_mode():
            encoded = self._speaker_encoder().encode_batch(waveform)
        values = encoded.squeeze().detach().cpu().tolist()
        return normalize_embedding([float(value) for value in values])

    def store_enrollment(self, db: Session, *, username: str, incoming: list[float]) -> VoiceProfile:
        user = db.query(UserProfile).filter_by(username=username).first()
        if not user:
            raise ValueError("unknown_user")
        profile = db.query(VoiceProfile).filter_by(username=username).first()
        if profile:
            previous = json.loads(profile.embedding)
            count = max(1, profile.sample_count)
            averaged = [
                ((float(old) * count) + new) / (count + 1)
                for old, new in zip(previous, incoming, strict=True)
            ]
            profile.embedding = json.dumps(normalize_embedding(averaged))
            profile.sample_count = count + 1
            profile.model = self.settings.ali_speaker_model
            profile.active = True
            profile.updated_at = utcnow()
        else:
            profile = VoiceProfile(
                username=username,
                embedding=json.dumps(incoming),
                sample_count=1,
                model=self.settings.ali_speaker_model,
                active=True,
                updated_at=utcnow(),
            )
            db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    def match_embedding(self, db: Session, incoming: list[float]) -> SpeakerMatch:
        profiles = db.query(VoiceProfile).filter_by(active=True).all()
        if not profiles:
            return SpeakerMatch(username=None, similarity=0.0, accepted=False)
        best_username = None
        best_similarity = -1.0
        for profile in profiles:
            stored = [float(value) for value in json.loads(profile.embedding)]
            score = cosine_similarity(incoming, stored)
            if score > best_similarity:
                best_username = profile.username
                best_similarity = score
        accepted = best_username is not None and best_similarity >= self.settings.ali_speaker_threshold
        return SpeakerMatch(
            username=best_username if accepted else None,
            similarity=best_similarity,
            accepted=accepted,
        )

    async def transcribe_async(self, audio_bytes: bytes) -> str:
        return await asyncio.to_thread(self.transcribe, audio_bytes)

    async def identify_async(self, db: Session, audio_bytes: bytes) -> SpeakerMatch:
        incoming = await asyncio.to_thread(self.speaker_embedding, audio_bytes)
        return self.match_embedding(db, incoming)

    async def enroll_async(self, db: Session, *, username: str, audio_bytes: bytes) -> VoiceProfile:
        incoming = await asyncio.to_thread(self.speaker_embedding, audio_bytes)
        return self.store_enrollment(db, username=username, incoming=incoming)
