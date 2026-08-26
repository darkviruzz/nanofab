"""The one indirection every user-visible string passes through (roadmap E10).

E10 asks for process descriptions *at the registration* — one source, in the
code, next to the thing being described — but "von Anfang an durch eine dünne
Übersetzungs-Indirektion, damit später ein Sprachkatalog darüber gelegt werden
kann, ohne die Registry anzufassen".

So this module is deliberately almost nothing. `text(key, default)` returns the
default until somebody installs a catalog, and then returns what the catalog says
instead. That is the whole mechanism.

**Why so little, on purpose.** Backlog B10 says a translation catalog with one
language in it is unproven infrastructure and should not be built yet, and it is
right. What is *not* free later is retrofitting the call site: 31 step
descriptions written as bare strings would be 31 places to edit the day a second
language arrives. A key beside each of them costs nothing today and is the entire
difference. So: the indirection now, the catalog when there is a second language.

**Keys are structural, not sentences.** `step.etch.wet.description` says what the
string is *for*; using the English text as its own key would make a catalog break
every time somebody fixed a typo.

The English text stays at the registration and is what a build with no catalog
shows — which means there is no second source to keep in sync, and a missing
translation degrades to English rather than to a key.
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class Catalog(Protocol):
    """Anything that can answer "what is this key in the current language?".

    A protocol rather than a class so a catalog can be a plain dict wrapper, a
    `gettext` translation, or a lookup in a file somebody edits — the choice B10
    defers, made without touching a single call site.
    """

    def lookup(self, key: str) -> str | None:
        """The translation for `key`, or `None` to fall back to the default."""


class MappingCatalog:
    """A catalog over a plain `{key: text}` mapping — enough for a test or a file."""

    def __init__(self, entries: Mapping[str, str]) -> None:
        self._entries = dict(entries)

    def lookup(self, key: str) -> str | None:
        return self._entries.get(key)


_catalog: Catalog | None = None


def set_catalog(catalog: Catalog | None) -> Catalog | None:
    """Install a catalog (or `None` for English); returns the previous one.

    Returning the previous one is what lets a test put it back, which matters
    because this is process-global state — the one kind of thing plan §5.2 is
    strict about. It is legitimate here for the same reason a locale is: it
    describes the person reading, not the sample being computed. Nothing in the
    kernel, the process contract or the runtime reads it, so no result depends on
    it and replay cannot see it.
    """
    global _catalog
    previous = _catalog
    _catalog = catalog
    return previous


def catalog() -> Catalog | None:
    """The installed catalog, or `None` when strings come out as written."""
    return _catalog


def text(key: str, default: str) -> str:
    """`default`, unless a catalog has something to say about `key`."""
    if _catalog is None:
        return default
    found = _catalog.lookup(key)
    return default if found is None else found


def step_description(step_id: str, default: str) -> str:
    """A registered step's long description, under a key derived from its id."""
    return text(f"step.{step_id}.description", default)


def step_name(step_id: str, default: str) -> str:
    """A registered step's display name, under a key derived from its id."""
    return text(f"step.{step_id}.name", default)
