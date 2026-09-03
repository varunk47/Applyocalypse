"""Suite-wide guards.

Before the submit gate the runner asks the ATS what the posting actually required. Many
tests here drive that flow with a real greenhouse.io job URL because that is what the
portal registry keys off, so without this the suite would make an outbound request per
run and then wait out its timeout. Stubbing it at the runner keeps the default answer
"nothing published", which is the same answer any non-Greenhouse portal gives. A test
that is about the schema overrides this with its own ``monkeypatch.setattr``.
"""

from __future__ import annotations

from typing import Any

import pytest

from applyocalypse_automation import runner


@pytest.fixture(autouse=True)
def no_published_schema_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runner, "fetch_questions", offline)
