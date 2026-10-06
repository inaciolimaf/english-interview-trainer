import asyncio

from api.realtime.orchestrator import CandidateTurn, Orchestrator, Segment


async def test_cancelling_the_end_of_turn_wait_keeps_transcriptions_alive():
    """Regression: a new speech_start cancels the end-of-turn check while it waits for the
    transcriptions; that must not cancel the transcriptions themselves."""
    release = asyncio.Event()

    async def transcription(seg: Segment):
        await release.wait()
        seg.result = {"text": "hello", "words": []}

    cand = CandidateTurn(start=0, started_at=None)
    seg = Segment(start=0, end=16_000)
    seg.task = asyncio.create_task(transcription(seg))
    cand.segments.append(seg)

    waiter = asyncio.create_task(Orchestrator._await_transcripts(None, cand))
    await asyncio.sleep(0.01)
    waiter.cancel()  # the candidate started talking again
    await asyncio.sleep(0.01)
    assert not seg.task.cancelled()

    release.set()
    await asyncio.wait_for(Orchestrator._await_transcripts(None, cand), 1)  # the next check completes
    assert seg.result == {"text": "hello", "words": []}
