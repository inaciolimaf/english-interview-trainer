"""Seed the database. Idempotent: safe to run any number of times.

- default user + default user_settings
- accepted_variants (section 8.5)
- tech_vocabulary (section 5.5), phonemes generated with espeak-ng

Usage (from backend/):  python scripts/seed.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from api.db.constants import DEFAULT_USER_ID  # noqa: E402
from api.db.models import AcceptedVariant, TechVocabulary, User, UserSettings  # noqa: E402
from api.db.session import SessionLocal, engine  # noqa: E402
from api.pronunciation.g2p import espeak_phonemes  # noqa: E402
from scripts.seed_data import ACCEPTED_VARIANTS, TECH_VOCABULARY  # noqa: E402


async def seed() -> None:
    async with SessionLocal() as db:
        await db.execute(
            insert(User)
            .values(id=DEFAULT_USER_ID, display_name="Candidate")
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        await db.execute(
            insert(UserSettings)
            .values(user_id=DEFAULT_USER_ID)
            .on_conflict_do_nothing(index_elements=[UserSettings.user_id])
        )

        variants = [
            {"word": w, "expected": e, "accepted": a, "note": n} for w, e, a, n in ACCEPTED_VARIANTS
        ]
        stmt = insert(AcceptedVariant).values(variants)
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_accepted_variants_word", set_={"note": stmt.excluded.note}
            )
        )

        vocab = [
            {
                "term": term,
                "phonemes": espeak_phonemes(say_as or term),
                "domain": domain,
                "common_mistake_note": note,
            }
            for term, say_as, domain, note in TECH_VOCABULARY
        ]
        stmt = insert(TechVocabulary).values(vocab)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[TechVocabulary.term],
                set_={
                    "phonemes": stmt.excluded.phonemes,
                    "domain": stmt.excluded.domain,
                    "common_mistake_note": stmt.excluded.common_mistake_note,
                    "updated_at": func.now(),
                },
            )
        )
        await db.commit()

        for model in (User, UserSettings, AcceptedVariant, TechVocabulary):
            count = await db.scalar(select(func.count()).select_from(model))
            print(f"{model.__tablename__:<20} {count}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
