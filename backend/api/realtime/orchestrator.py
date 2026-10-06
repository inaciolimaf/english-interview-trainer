"""Per-connection turn orchestrator (section 7). The server is the source of truth for
the conversation state; the client mirrors it.

    IDLE → LISTENING → THINKING → SPEAKING → LISTENING
                 ▲         │          │ (VAD speech)
                 └─────────┘          ▼
               (candidate resumed)  DUCKING → SPEAKING (noise/backchannel)
                                       └────→ LISTENING (interruption confirmed)

Audio: the client streams PCM16 16 kHz continuously. Each VAD speech segment is
transcribed as soon as it ends, so at end-of-turn only the last segment is pending —
long answers don't make the reply slower.
"""

import asyncio
import logging
import struct
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np
from sqlalchemy import func, select

from api.db.models import InterviewSession, JobPosting, Resume, Turn, UserSettings
from api.db.session import SessionLocal
from api.interview.prompts import (
    InterviewContext, interviewer_system_prompt, strip_end_marker, time_note,
)
from api.analysis.pipeline import TurnJob
from api.analysis.worker import AnalysisWorker, ReportJob
from api.llm.client import LLMClient
from api.realtime import hub
from api.realtime.history import TurnRecord, build_messages, join_sentences, spoken_prefix
from api.realtime.model_client import ModelClient, ModelServerError
from api.realtime.sentence_splitter import SentenceSplitter
from api.realtime.turn_policy import (
    Decision, TurnPolicy, decide_end_of_turn, is_backchannel, is_substantive,
)

log = logging.getLogger("realtime")

SR = 16_000
BYTES_PER_SAMPLE = 2
TURN_PREROLL_MS = 1000  # audio kept before speech_start (spec 7.5: ~1 s)
KEEP_AUDIO_MS = 2000  # mic history kept outside a candidate turn
SEGMENT_PREROLL_MS = 300  # VAD onset delay compensation per segment
VAD_REDEMPTION_MS = 300  # client VAD waits this long before emitting speech_end
INTERRUPT_REPORT_TIMEOUT_S = 1.5
# Server-side safety net for the browser VAD: if a speech segment is open but the audio has
# been quiet this long, close it as if speech_end had arrived (a missed speech_end used to
# leave the turn open forever).
SILENCE_WATCHDOG_MS = 1500
VOICE_RMS_MIN = 300  # int16 RMS; quieter than this is never voice
VOICE_OVER_FLOOR = 2.5  # voice = louder than 2.5× the recent noise floor
NOISE_WINDOW_FRAMES = 250  # ~5 s of 20 ms frames for the noise-floor estimate
TIME_UPDATE_EVERY_S = 10
FILLER_PROMPT = "Um, so, uh, I think... hmm, like, you know, "
TOUGH_CUT_IN_S = 180  # tough style: take the floor after ~3 min of uninterrupted answer
END_MARKER_MIN_ELAPSED = 0.7  # ignore an early end-of-interview token before 70% of the time
HARD_STOP_AFTER_S = 180  # past the end: close after the current reply no matter what
CUT_IN_NOTE = (
    "[You are cutting in: the candidate has been talking for over three minutes without a "
    "pause. Politely interrupt, sum up what you heard in a few words and steer them with a "
    "focused question.]"
)
AUDIO_HEADER = struct.Struct("<IHH")  # turn_id, sentence_idx, reserved


class State(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    DUCKING = "DUCKING"


@dataclass
class Segment:
    start: int  # absolute sample index
    end: int | None = None
    task: asyncio.Task | None = None  # transcription
    result: dict | None = None


@dataclass
class CandidateTurn:
    start: int
    started_at: datetime
    segments: list[Segment] = field(default_factory=list)
    speaking: bool = False
    last_speech_end: float = 0.0  # monotonic time of the last speech_end

    @property
    def open_segment(self) -> Segment | None:
        return self.segments[-1] if self.segments and self.segments[-1].end is None else None


@dataclass
class Reply:
    """One interviewer response being generated/played."""

    turn_id: int
    task: asyncio.Task | None = None
    sentences: list[str] = field(default_factory=list)  # split so far (incl. not yet spoken)
    sent: list[str] = field(default_factory=list)  # synthesized and sent to the client
    tail: str = ""  # unsplit remainder when generation stopped
    ends_interview: bool = False  # the LLM emitted the end-of-interview token
    cut_in: bool = False  # tough-style cut-in: the candidate is probably still talking
    llm_done: bool = False
    playback_done: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    timings: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return join_sentences([*self.sentences, self.tail])


SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]


class Orchestrator:
    def __init__(
        self, session_id: uuid.UUID, send_json: SendJson, send_bytes: SendBytes,
        llm: LLMClient, models: ModelClient, on_ended: Callable[[], Awaitable[None]] | None = None,
        analysis: AnalysisWorker | None = None,
    ) -> None:
        self.session_id = session_id
        self._send_json, self._send_bytes = send_json, send_bytes
        self._send_lock = asyncio.Lock()
        self.llm, self.models = llm, models
        self.on_ended = on_ended
        self.analysis = analysis
        self.session_meta: dict = {}
        self.style = "neutral"
        self.tough_cut_in_s = TOUGH_CUT_IN_S
        self.cut_in_task: asyncio.Task | None = None
        self.ignore_speech_until_end = False  # cut-in reply: the ongoing speech is not a barge-in

        self.state = State.IDLE
        self.turn_id = 0
        self.history: list[TurnRecord] = []
        self.next_idx = 0
        self.mode = "auto"
        self.policy = TurnPolicy()
        self.voice: str | None = None
        self.speed = 1.0
        self.system_prompt = ""
        self.session_started: datetime | None = None
        self.duration_s = 0

        # mic audio: absolute sample index of buf[0] is buf_base
        self.buf = bytearray()
        self.buf_base = 0
        self.listen_start = 0

        self.cand: CandidateTurn | None = None
        # last candidate turn: in history but not persisted until the reply's first audio
        # (until then the candidate may resume talking and the turn is reopened)
        self.unsaved_cand: tuple[TurnRecord, CandidateTurn, dict] | None = None
        self.reply: Reply | None = None
        self.eot_task: asyncio.Task | None = None
        self.bargein_task: asyncio.Task | None = None
        self.bargein_start = 0  # candidate-turn start if confirmed (with ~1 s pre-roll)
        self.bargein_speech = 0  # where the interrupting speech itself starts
        self.reply_floor = 0  # mic position when the current reply started (pre-roll limit)
        self.speech_ended = asyncio.Event()
        self.pending_interruption: tuple[Reply, TurnRecord, asyncio.Future] | None = None
        self.timer_task: asyncio.Task | None = None
        self.closed = False
        self.frame_rms: list[float] = []  # recent frame energies (noise floor)
        self.last_voice_pos = 0  # mic position of the last frame that sounded like voice

    # ------------------------------------------------------------------ setup
    async def start(self) -> None:
        async with SessionLocal() as db:
            session = await db.get(InterviewSession, self.session_id)
            if session is None:
                raise LookupError("session not found")
            settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == session.user_id))
            turns = (await db.scalars(
                select(Turn).where(Turn.session_id == self.session_id).order_by(Turn.idx)
            )).all()
            self.next_idx = (await db.scalar(
                select(func.coalesce(func.max(Turn.idx), -1)).where(Turn.session_id == self.session_id)
            )) + 1
            job = await db.get(JobPosting, session.job_posting_id) if session.job_posting_id else None
            resume = await db.get(Resume, session.resume_id) if session.resume_id else None
            if session.status == "abandoned":  # rejoined after a dropped connection
                session.status = "active"
                await db.commit()

        self.mode = settings.turn_taking_mode
        self.policy = TurnPolicy(silence_ms=settings.end_of_turn_silence_ms)
        self.voice, self.speed = settings.tts_voice, settings.tts_speed
        self.style = session.interviewer_style
        self.session_meta = {"user_id": session.user_id, "seniority": session.seniority,
                             "type": session.type, "feedback_mode": session.feedback_mode}
        hub.register(self.session_id, self.send)
        self.system_prompt = interviewer_system_prompt(InterviewContext(
            session_type=session.type, seniority=session.seniority, style=session.interviewer_style,
            duration_min=session.duration_min, plan=session.plan or {},
            job={"title": job.title, "company": job.company, "parsed": job.parsed} if job else None,
            profile=resume.parsed_profile if resume else None,
        ))
        self.session_started = session.started_at
        self.duration_s = session.duration_min * 60
        self.history = [
            TurnRecord(t.role, t.full_text, t.spoken_text, t.interrupted) for t in turns
        ]
        await self.send({"type": "config", "turn_taking_mode": self.mode, "turn_id": self.turn_id})
        self.timer_task = asyncio.create_task(self._time_updates())
        if not self.history or self.history[-1].role == "candidate":
            self._start_reply()  # greeting, or answer a turn left unanswered (reconnect)
        else:
            await self._set_state(State.LISTENING)

    async def close(self) -> None:
        self.closed = True
        hub.unregister(self.session_id, self.send)
        self._cancel_tasks()

    def _cancel_tasks(self) -> None:
        for task in (self.eot_task, self.bargein_task, self.timer_task, self.cut_in_task,
                     self.reply.task if self.reply else None):
            if task:
                task.cancel()

    # ------------------------------------------------------------- transport
    async def send(self, msg: dict) -> None:
        if self.closed:
            return
        async with self._send_lock:
            await self._send_json(msg)

    async def _send_sentence(self, reply: Reply, idx: int, text: str, words: list, sample_rate: int,
                             pcm: bytes) -> None:
        async with self._send_lock:  # JSON + binary must stay adjacent
            await self._send_json({
                "type": "tts_sentence", "turn_id": reply.turn_id, "sentence_idx": idx,
                "text": text, "words": words, "sample_rate": sample_rate,
            })
            await self._send_bytes(AUDIO_HEADER.pack(reply.turn_id, idx, 0) + pcm)

    async def _set_state(self, state: State) -> None:
        self.state = state
        if state == State.LISTENING:
            self.listen_start = self.pos
        await self.send({"type": "state", "state": state.value, "turn_id": self.turn_id})

    async def _error(self, message: str) -> None:
        log.error(message)
        await self.send({"type": "error", "message": message})

    def _spawn(self, coro, name: str) -> asyncio.Task:
        """Background task whose crash is logged and shown, never silently lost."""
        task = asyncio.create_task(coro, name=name)

        def done(t: asyncio.Task) -> None:
            if t.cancelled() or t.exception() is None or self.closed:
                return
            log.error("session %s: %s task crashed", str(self.session_id)[:8], name, exc_info=t.exception())
            asyncio.create_task(self._error(f"Internal error in {name}: {t.exception()!r}"))

        task.add_done_callback(done)
        return task

    # ------------------------------------------------------------------ audio
    @property
    def pos(self) -> int:
        return self.buf_base + len(self.buf) // BYTES_PER_SAMPLE

    def audio(self, start: int, end: int | None = None) -> bytes:
        s = max(0, start - self.buf_base) * BYTES_PER_SAMPLE
        e = (end - self.buf_base) * BYTES_PER_SAMPLE if end is not None else len(self.buf)
        return bytes(self.buf[s:e])

    def _trim(self) -> None:
        keep_from = self.pos - KEEP_AUDIO_MS * SR // 1000
        if self.cand:
            keep_from = min(keep_from, self.cand.start)
        drop = max(0, keep_from - self.buf_base)
        if drop:
            del self.buf[: drop * BYTES_PER_SAMPLE]
            self.buf_base += drop

    def on_audio(self, frame: bytes) -> None:
        self.buf.extend(frame)
        if len(frame) < 2:
            return
        rms = float(np.sqrt(np.mean(np.frombuffer(frame[: len(frame) // 2 * 2], dtype="<i2").astype(np.float32) ** 2)))
        self.frame_rms.append(rms)
        if len(self.frame_rms) > NOISE_WINDOW_FRAMES:
            del self.frame_rms[0]
        floor = float(np.percentile(self.frame_rms, 10))
        if rms > max(VOICE_RMS_MIN, VOICE_OVER_FLOOR * floor):
            self.last_voice_pos = self.pos
        self._silence_watchdog()

    def _silence_watchdog(self) -> None:
        cand = self.cand
        if self.state != State.LISTENING or cand is None or cand.open_segment is None or self.mode != "auto":
            return
        quiet_ms = (self.pos - max(self.last_voice_pos, cand.open_segment.start)) * 1000 // SR
        if quiet_ms >= SILENCE_WATCHDOG_MS:
            log.warning("session %s: no speech_end from the browser after %d ms of silence; closing the segment",
                        str(self.session_id)[:8], quiet_ms)
            self.speech_ended.set()
            self._close_segment(quiet_s=quiet_ms / 1000)
            self._schedule_eot()

    # --------------------------------------------------------------- messages
    async def on_message(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "vad":
            log.info("session %s: vad %s (state %s)", str(self.session_id)[:8], msg.get("event"), self.state)
            if self.mode == "auto":
                if msg.get("event") == "speech_start":
                    await self._on_speech_start()
                elif msg.get("event") == "speech_end":
                    await self._on_speech_end()
        elif kind == "ptt":
            if self.mode == "push_to_talk":
                await (self._on_ptt_down() if msg.get("event") == "down" else self._on_ptt_up())
        elif kind == "interrupted":
            self._on_interrupted_report(msg)
        elif kind == "playback_done":
            await self._on_playback_done(msg.get("turn_id"))
        elif kind == "set_mode" and msg.get("mode") in ("auto", "push_to_talk"):
            self.mode = msg["mode"]
            await self.send({"type": "config", "turn_taking_mode": self.mode, "turn_id": self.turn_id})

    # ---------------------------------------------------------- speech events
    async def _on_speech_start(self) -> None:
        if self.ignore_speech_until_end:
            return  # the candidate is still finishing the sentence we cut into
        self.speech_ended.clear()
        if self.state == State.SPEAKING:
            await self._begin_bargein()
        elif self.state == State.THINKING:
            await self._resume_candidate()
            self._open_segment()
        elif self.state == State.LISTENING:
            self._open_segment()

    async def _on_speech_end(self) -> None:
        if self.ignore_speech_until_end:
            self.ignore_speech_until_end = False
            return
        self.speech_ended.set()
        if self.state == State.LISTENING and self.cand:
            self._close_segment()
            self._schedule_eot()

    def _open_segment(self) -> None:
        if self.eot_task:
            self.eot_task.cancel()
        now = self.pos
        if self.cand is None:
            start = max(self.listen_start, now - TURN_PREROLL_MS * SR // 1000)
            self.cand = CandidateTurn(start=start, started_at=datetime.now(UTC))
            if self.style == "tough":
                self.cut_in_task = self._spawn(self._tough_cut_in(self.cand), "cut-in")
        if self.cand.open_segment:
            return
        prev_end = self.cand.segments[-1].end if self.cand.segments else self.cand.start
        start = max(prev_end, now - SEGMENT_PREROLL_MS * SR // 1000)
        self.cand.segments.append(Segment(start=start))
        self.cand.speaking = True

    def _close_segment(self, quiet_s: float = VAD_REDEMPTION_MS / 1000) -> None:
        """``quiet_s``: how long the speaker has already been silent (VAD redemption, or the
        silence the watchdog measured)."""
        cand = self.cand
        seg = cand.open_segment if cand else None
        if seg is None:
            return
        seg.end = self.pos
        cand.speaking = False
        cand.last_speech_end = time.monotonic() - quiet_s
        # a disfluent prompt keeps Whisper from silently dropping "um"/"uh" (needed for fluency)
        prompt = FILLER_PROMPT + " ".join(s.result["text"] for s in cand.segments if s.result)[-200:]
        seg.task = self._spawn(self._transcribe_segment(seg, prompt), "transcription")

    async def _transcribe_segment(self, seg: Segment, prompt: str | None) -> None:
        seg.result = await self.models.transcribe(self.audio(seg.start, seg.end), prompt)
        if self.cand and seg in self.cand.segments:
            await self.send({"type": "transcript_partial", "text": self._cand_text(self.cand)})

    @staticmethod
    def _cand_text(cand: CandidateTurn) -> str:
        return " ".join(s.result["text"] for s in cand.segments if s.result and s.result["text"]).strip()

    # ------------------------------------------------------------ end of turn
    def _schedule_eot(self) -> None:
        if self.eot_task:
            self.eot_task.cancel()
        self.eot_task = self._spawn(self._eot_loop(), "end-of-turn")

    async def _eot_loop(self) -> None:
        cand = self.cand
        probability: float | None = None
        checked = False
        try:
            for threshold in (self.policy.check_after_ms, self.policy.silence_ms, self.policy.max_silence_ms):
                silence = (time.monotonic() - cand.last_speech_end) * 1000
                if silence < threshold:
                    await asyncio.sleep((threshold - silence) / 1000)
                if not checked:
                    pcm = self.audio(cand.start, cand.segments[-1].end)
                    probability, _ = await asyncio.gather(
                        self.models.end_of_turn(pcm), self._await_transcripts(cand)
                    )
                    checked = True
                # the sleep may wake a few ms early: never report less silence than we waited for,
                # otherwise the last check (max silence) could say "wait" and the turn never ended
                silence = max(threshold, (time.monotonic() - cand.last_speech_end) * 1000)
                text = self._cand_text(cand)
                decision = decide_end_of_turn(self.policy, silence, probability, text)
                log.info("session %s: end-of-turn %s (silence %d ms, P(end)=%s, text ends %r)",
                         str(self.session_id)[:8], decision, silence,
                         f"{probability:.2f}" if probability is not None else None, text[-40:])
                if decision == Decision.END:
                    await self._end_candidate_turn(probability)
                    return
        except ModelServerError as exc:
            await self._error(f"Model server error: {exc}")
            self.cand = None

    async def _await_transcripts(self, cand: CandidateTurn) -> None:
        """Wait until every closed segment of the turn has its transcript.

        The segment tasks are shielded: this wait is cancelled whenever the candidate starts
        talking again, and cancelling a plain gather() would cancel the transcriptions too —
        those segments then never got a result and every later end-of-turn check died
        silently (the turn never closed). A segment left without a result is transcribed again.
        """
        for seg in cand.segments:
            if seg.end is not None and seg.result is None and (seg.task is None or seg.task.cancelled()):
                seg.task = self._spawn(self._transcribe_segment(seg, None), "transcription")
        tasks = [s.task for s in cand.segments if s.task]
        if tasks:
            await asyncio.gather(*(asyncio.shield(t) for t in tasks))

    async def _finalize_open_answer(self) -> None:
        """The interview ends while the candidate's turn is still open: keep that answer
        (persisted and analyzed) instead of dropping it."""
        cand = self.cand
        if cand is None or self.state not in (State.LISTENING, State.IDLE):
            return
        if self.eot_task:
            self.eot_task.cancel()
        self._close_segment()
        try:
            await asyncio.wait_for(self._await_transcripts(cand), 15)
        except (TimeoutError, ModelServerError):
            log.warning("session %s: could not transcribe the last answer before ending", str(self.session_id)[:8])
        text = self._cand_text(cand)
        if not text:
            return
        end = cand.segments[-1].end
        words = []
        for seg in cand.segments:
            offset_ms = (seg.start - cand.start) * 1000 // SR
            for w in (seg.result or {}).get("words", []):
                words.append({**w, "start_ms": w["start_ms"] + offset_ms, "end_ms": w["end_ms"] + offset_ms})
        record = TurnRecord("candidate", text, text)
        self.history.append(record)
        self.cand = None
        await self._persist_candidate(record, {
            "pcm": self.audio(cand.start, end), "question": self._last_question(),
            "audio_ms": (end - cand.start) * 1000 // SR, "asr_words": words,
            "started_at": cand.started_at, "ended_at": datetime.now(UTC),
        })

    async def _tough_cut_in(self, cand: CandidateTurn) -> None:
        """Section 9.4: the tough interviewer takes the floor after ~3 min of answer."""
        await asyncio.sleep(self.tough_cut_in_s)
        if self.cand is not cand or self.state != State.LISTENING:
            return
        log.info("tough interviewer cutting in after %ss", self.tough_cut_in_s)
        if self.eot_task:
            self.eot_task.cancel()
        still_talking = cand.open_segment is not None
        self._close_segment()
        self.ignore_speech_until_end = still_talking
        try:
            await self._await_transcripts(cand)
        except ModelServerError as exc:
            await self._error(f"Model server error: {exc}")
            return
        if self.cand is cand:
            await self._end_candidate_turn(None, cut_in=True)

    async def _end_candidate_turn(self, probability: float | None, cut_in: bool = False) -> None:
        cand = self.cand
        text = self._cand_text(cand)
        if not text:  # noise only
            self.cand = None
            return
        t_eot = time.monotonic()
        end = cand.segments[-1].end
        words = []
        for seg in cand.segments:
            offset_ms = (seg.start - cand.start) * 1000 // SR
            for w in (seg.result or {}).get("words", []):
                words.append({**w, "start_ms": w["start_ms"] + offset_ms, "end_ms": w["end_ms"] + offset_ms})
        record = TurnRecord("candidate", text, text)
        meta = {
            "pcm": self.audio(cand.start, end), "question": self._last_question(),
            "audio_ms": (end - cand.start) * 1000 // SR, "asr_words": words,
            "started_at": cand.started_at, "ended_at": datetime.now(UTC),
            "eot_probability": probability, "speech_end": cand.last_speech_end, "eot_at": t_eot,
        }
        self.history.append(record)
        self.unsaved_cand = (record, cand, meta)
        self.cand = None
        await self.send({"type": "transcript_final", "text": text})
        self._start_reply(cut_in=cut_in)

    async def _resume_candidate(self) -> None:
        """Candidate kept talking while we were THINKING: drop the reply, reopen their turn."""
        if self.reply and self.reply.task:
            self.reply.task.cancel()
        self.reply = None
        if self.unsaved_cand:
            record, self.cand, _ = self.unsaved_cand
            self.history.remove(record)
            self.unsaved_cand = None
        await self._set_state(State.LISTENING)
        # keep the original turn start: _set_state reset listen_start
        if self.cand:
            self.listen_start = self.cand.start

    # ---------------------------------------------------------------- replies
    def _start_reply(self, cut_in: bool = False) -> None:
        self.reply_floor = self.pos
        self.turn_id += 1
        reply = Reply(turn_id=self.turn_id, cut_in=cut_in)
        self.reply = reply
        reply.task = self._spawn(self._run_reply(reply), "reply")

    async def _run_reply(self, reply: Reply) -> None:
        await self._set_state(State.THINKING)
        self._resolve_pending_interruption()
        # transient notes go last so the cached prefix (system prompt + history) is untouched
        messages = build_messages(self.system_prompt, self.history)
        messages.append({"role": "system", "content": time_note(self.remaining_s, self.duration_s)})
        if reply.cut_in:
            messages.append({"role": "system", "content": CUT_IN_NOTE})
        sentence_q: asyncio.Queue[str | None] = asyncio.Queue()
        t0 = time.monotonic()
        reply.timings["t0"] = t0

        async def on_retry(attempt: int, exc: Exception) -> None:
            await self.send({"type": "warning", "message": f"LLM request failed, retrying ({attempt})…"})

        async def produce() -> None:
            splitter = SentenceSplitter()
            try:
                async for token in self.llm.stream(messages, on_retry=on_retry):
                    reply.timings.setdefault("llm_first_token", time.monotonic())
                    for sentence in splitter.feed(token):
                        await emit(sentence)
                for sentence in splitter.flush():
                    await emit(sentence)
                reply.llm_done = True
            finally:
                reply.tail = strip_end_marker(splitter.buffer)[0]
                await sentence_q.put(None)

        async def emit(sentence: str) -> None:
            clean, ended = strip_end_marker(sentence)
            reply.ends_interview |= ended
            if clean:
                reply.sentences.append(clean)
                await sentence_q.put(clean)

        producer = asyncio.create_task(produce())
        try:
            idx = 0
            while (sentence := await sentence_q.get()) is not None:
                reply.timings.setdefault("first_sentence", time.monotonic())
                words, pcm, rate = [], bytearray(), 24_000
                # word timings from the model server are already relative to the sentence start
                async for meta, chunk in self.models.tts(sentence, self.voice, self.speed):
                    words += meta["words"]
                    rate = meta["sample_rate"]
                    pcm.extend(chunk)
                await self._send_sentence(reply, idx, sentence, words, rate, bytes(pcm))
                reply.sent.append(sentence)
                if idx == 0:
                    reply.timings["first_audio"] = time.monotonic()
                    await self._on_first_audio(reply)
                idx += 1
            await producer  # surface LLM errors
            if not reply.sent:
                await self._error("The interviewer produced an empty reply.")
                self.reply = None
                await self._set_state(State.LISTENING)
                return
            await self.send({"type": "tts_end", "turn_id": reply.turn_id, "n_sentences": len(reply.sent)})
        except asyncio.CancelledError:
            producer.cancel()  # aborts the LLM HTTP stream
            raise
        except ModelServerError as exc:
            producer.cancel()
            await self._error(f"Model server error: {exc}")
            await self._abort_reply(reply)
        except Exception as exc:  # noqa: BLE001 — LLM failure after retries
            producer.cancel()
            await self._error(f"LLM error: {exc!r}")
            await self._abort_reply(reply)

    async def _abort_reply(self, reply: Reply) -> None:
        if reply.sent:  # client has audio: let it finish, record what was sent
            await self.send({"type": "tts_end", "turn_id": reply.turn_id, "n_sentences": len(reply.sent)})
        else:
            self.reply = None
            await self._set_state(State.LISTENING)

    async def _on_first_audio(self, reply: Reply) -> None:
        await self._set_state(State.SPEAKING)
        # the candidate turn is final now: persist it
        if self.unsaved_cand:
            record, _, meta = self.unsaved_cand
            self.unsaved_cand = None
            await self._persist_candidate(record, meta)
            lat = {
                "turn_id": reply.turn_id,
                "end_of_turn_wait_ms": round((meta["eot_at"] - meta["speech_end"]) * 1000),
                "llm_first_token_ms": _ms(reply.timings, "t0", "llm_first_token"),
                "first_sentence_ms": _ms(reply.timings, "t0", "first_sentence"),
                "first_audio_ms": _ms(reply.timings, "t0", "first_audio"),
                "total_ms": round((reply.timings["first_audio"] - meta["speech_end"]) * 1000),
            }
            log.info("latency %s", lat)
            await self.send({"type": "latency", **lat})
        self._trim()

    async def _on_playback_done(self, turn_id: int | None) -> None:
        reply = self.reply
        if reply is None or turn_id != reply.turn_id:
            return  # stale
        reply.playback_done = True
        record = TurnRecord("interviewer", reply.full_text, reply.full_text)
        self.history.append(record)
        await self._persist_interviewer(reply, record)
        self.reply = None
        if self._should_end_after(reply):
            await self.end_session()
            return
        if self.state == State.DUCKING:
            return  # barge-in check still running; it decides the next state
        await self._set_state(State.LISTENING)

    def _should_end_after(self, reply: Reply) -> bool:
        """Time management (9.2): the interviewer said goodbye, or we are well past the end."""
        elapsed_fraction = 1 - self.remaining_s / self.duration_s if self.duration_s else 1
        if reply.ends_interview:
            if elapsed_fraction >= END_MARKER_MIN_ELAPSED:
                return True
            log.warning("ignoring early end-of-interview token at %.0f%% of the time", elapsed_fraction * 100)
        return self.remaining_s <= -HARD_STOP_AFTER_S

    @property
    def remaining_s(self) -> float:
        if self.session_started is None:
            return float(self.duration_s)
        return self.duration_s - (datetime.now(UTC) - self.session_started).total_seconds()

    # --------------------------------------------------------------- barge-in
    async def _begin_bargein(self) -> None:
        self.state = State.DUCKING
        self.bargein_start = max(self.reply_floor, self.pos - TURN_PREROLL_MS * SR // 1000)
        self.bargein_speech = max(self.reply_floor, self.pos - SEGMENT_PREROLL_MS * SR // 1000)
        await self.send({"type": "duck"})
        await self.send({"type": "state", "state": State.DUCKING.value, "turn_id": self.turn_id})
        self.bargein_task = self._spawn(self._bargein_check(), "barge-in")

    async def _bargein_check(self) -> None:
        """Section 7.5: < 400 ms → noise; whole utterance is a backchannel → continue;
        otherwise (or still talking after bargein_max_wait_ms) → interruption."""
        p = self.policy
        started = time.monotonic()
        wait_s = p.bargein_min_ms / 1000
        try:
            while True:
                try:
                    await asyncio.wait_for(self.speech_ended.wait(), wait_s)
                except TimeoutError:
                    pass
                elapsed_ms = (time.monotonic() - started) * 1000
                if self.speech_ended.is_set():
                    if elapsed_ms < p.bargein_min_ms:
                        return await self._cancel_bargein()  # cough / noise
                    full = await self.models.transcribe(self.audio(self.bargein_speech))
                    log.info("barge-in utterance: %r", full["text"])
                    if is_backchannel(full["text"]):
                        return await self._cancel_bargein()
                    return await self._confirm_interruption()
                if elapsed_ms >= p.bargein_max_wait_ms:
                    return await self._confirm_interruption()  # too long for a backchannel
                check_started = time.monotonic()
                snippet = await self.models.transcribe(self.audio(self.bargein_speech))
                log.info("barge-in snippet at %d ms: %r", elapsed_ms, snippet["text"])
                if is_substantive(snippet["text"]):
                    return await self._confirm_interruption()
                wait_s = max(0.0, p.bargein_recheck_ms / 1000 - (time.monotonic() - check_started))
        except ModelServerError as exc:
            await self._error(f"Model server error: {exc}")
            await self._cancel_bargein()

    async def _cancel_bargein(self) -> None:
        await self.send({"type": "unduck"})
        if self.reply is None:  # interviewer finished meanwhile
            await self._set_state(State.LISTENING)
        else:
            await self._set_state(State.SPEAKING)

    async def _confirm_interruption(self) -> None:
        reply = self.reply
        if reply is not None:
            if reply.task:
                reply.task.cancel()
            await self.send({"type": "stop_playback", "turn_id": reply.turn_id})
            record = TurnRecord("interviewer", reply.full_text, join_sentences(reply.sent), interrupted=True)
            self.history.append(record)
            report: asyncio.Future = asyncio.get_running_loop().create_future()
            self.pending_interruption = (reply, record, report)
            asyncio.create_task(self._finish_interruption(reply, record, report))
            self.reply = None
        self.turn_id += 1  # anything still in flight for the old turn is stale now
        await self._set_state(State.LISTENING)
        # the speech that interrupted us starts the candidate's turn (with ~1 s pre-roll)
        self.listen_start = self.bargein_start
        self.cand = CandidateTurn(start=self.bargein_start, started_at=datetime.now(UTC))
        self.cand.segments.append(Segment(start=self.bargein_start))
        self.cand.speaking = True
        if self.speech_ended.is_set():  # they already stopped talking
            self._close_segment()
            self._schedule_eot()

    def _on_interrupted_report(self, msg: dict) -> None:
        if not self.pending_interruption:
            return
        reply, record, report = self.pending_interruption
        if msg.get("turn_id") != reply.turn_id or report.done():
            return
        report.set_result(spoken_prefix(reply.sent, int(msg.get("sentence_idx", 0)),
                                        int(msg.get("char_offset", 0))))

    async def _finish_interruption(self, reply: Reply, record: TurnRecord, report: asyncio.Future) -> None:
        try:
            record.spoken_text = await asyncio.wait_for(report, INTERRUPT_REPORT_TIMEOUT_S)
        except TimeoutError:
            log.warning("no interruption report from client; assuming every sent sentence was heard")
        if self.pending_interruption and self.pending_interruption[1] is record:
            self.pending_interruption = None
        record.full_text = reply.full_text  # generation may have advanced before cancel
        await self._persist_interviewer(reply, record)

    def _resolve_pending_interruption(self) -> None:
        """A reply is starting: use the client report if it already arrived."""
        if self.pending_interruption:
            _, record, report = self.pending_interruption
            if report.done():
                record.spoken_text = report.result()

    # ------------------------------------------------------------ push-to-talk
    async def _on_ptt_down(self) -> None:
        self.speech_ended.clear()
        if self.state in (State.SPEAKING, State.DUCKING):
            if self.bargein_task:
                self.bargein_task.cancel()
            self.bargein_start = self.bargein_speech = max(0, self.pos - 200 * SR // 1000)
            await self._confirm_interruption()
        elif self.state == State.THINKING:
            await self._resume_candidate()
            self._open_segment()
        else:
            self._open_segment()

    async def _on_ptt_up(self) -> None:
        self.speech_ended.set()
        if not self.cand:
            return
        self._close_segment()
        try:
            await self._await_transcripts(self.cand)
        except ModelServerError as exc:
            await self._error(f"Model server error: {exc}")
            self.cand = None
            return
        await self._end_candidate_turn(None)

    # ------------------------------------------------------------- persistence
    async def _persist_candidate(self, record: TurnRecord, meta: dict) -> None:
        turn = Turn(
            id=uuid.uuid4(), session_id=self.session_id, idx=self._take_idx(), role="candidate",
            full_text=record.full_text, spoken_text=record.spoken_text,
            started_at=meta["started_at"], ended_at=meta["ended_at"],
            audio_ms=meta["audio_ms"], asr_words=meta["asr_words"], analysis_status="pending",
        )
        async with SessionLocal() as db:
            db.add(turn)
            await db.commit()
        if self.analysis:  # background: pronunciation runs at low GPU priority, between turns
            self.analysis.submit(TurnJob(
                turn_id=turn.id, turn_idx=turn.idx, session_id=self.session_id,
                user_id=self.session_meta["user_id"], pcm=meta.pop("pcm"), words=meta["asr_words"],
                text=record.full_text, question=meta["question"], seniority=self.session_meta["seniority"],
                session_type=self.session_meta["type"], feedback_mode=self.session_meta["feedback_mode"],
                llm=self.llm,
            ))

    def _last_question(self) -> str:
        return next((t.spoken_text for t in reversed(self.history) if t.role == "interviewer"), "")

    async def _persist_interviewer(self, reply: Reply, record: TurnRecord) -> None:
        async with SessionLocal() as db:
            db.add(Turn(
                session_id=self.session_id, idx=self._take_idx(), role="interviewer",
                full_text=record.full_text, spoken_text=record.spoken_text,
                interrupted=record.interrupted,
                interrupted_at_char=len(record.spoken_text) if record.interrupted else None,
                started_at=reply.started_at, ended_at=datetime.now(UTC),
            ))
            await db.commit()

    def _take_idx(self) -> int:
        idx, self.next_idx = self.next_idx, self.next_idx + 1
        return idx

    async def end_session(self) -> None:
        if self.closed:
            return
        await self._finalize_open_answer()
        self._cancel_tasks()
        if self.unsaved_cand:  # answered by nobody, but it is still part of the interview
            record, _, meta = self.unsaved_cand
            self.unsaved_cand = None
            await self._persist_candidate(record, meta)
        async with SessionLocal() as db:
            session = await db.get(InterviewSession, self.session_id)
            session.status = "completed"
            session.ended_at = datetime.now(UTC)
            await db.commit()
        if self.analysis:  # after the pending turn analyses: report, then drills
            self.analysis.submit(ReportJob(self.session_id, self.llm))
        await self.send({"type": "session_ended", "session_id": str(self.session_id)})
        self.closed = True
        if self.on_ended:
            await self.on_ended()

    async def _time_updates(self) -> None:
        while True:
            elapsed = (datetime.now(UTC) - self.session_started).total_seconds()
            await self.send({"type": "time", "remaining_s": max(0, round(self.duration_s - elapsed))})
            await asyncio.sleep(TIME_UPDATE_EVERY_S)


def _ms(timings: dict, a: str, b: str) -> int | None:
    return round((timings[b] - timings[a]) * 1000) if a in timings and b in timings else None
