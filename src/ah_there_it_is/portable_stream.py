"""Bounded, disk-backed reader for portable inventory JSON."""

from __future__ import annotations

import codecs
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any, BinaryIO


_DEFAULT_CHUNK_SIZE = 64 * 1024
_SPOOL_PATHS = {
    ("inventory", "categories"): "categories",
    ("inventory", "locations"): "locations",
    ("inventory", "items"): "items",
    ("history", "events"): "events",
}


class PortableInputError(ValueError):
    """Portable JSON cannot be decoded without weakening strictness."""


@dataclass(frozen=True)
class SpoolMarker:
    section: str


@dataclass
class PortableInputWorkspace:
    root: Path
    structure: Any = None
    counts: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in _SPOOL_PATHS.values()}
    )
    _writers: dict[str, Any] = field(default_factory=dict, repr=False)

    def append(self, section: str, value: Any) -> int:
        writer = self._writers.get(section)
        if writer is None:
            writer = (self.root / f"{section}.jsonl").open("w", encoding="utf-8")
            self._writers[section] = writer
        writer.write(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        )
        writer.write("\n")
        index = self.counts[section]
        self.counts[section] = index + 1
        return index

    def finish(self) -> None:
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()

    def iter_records(self, section: str) -> Iterator[Any]:
        if section not in self.counts:
            raise KeyError(section)
        path = self.root / f"{section}.jsonl"
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                yield json.loads(line)


class _ChunkedText:
    def __init__(self, source: BinaryIO, chunk_size: int) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        self.source = source
        self.chunk_size = chunk_size
        self.buffer = ""
        self.position = 0
        self.offset = 0
        self.eof = False
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")

    def peek(self) -> str:
        if self.position >= len(self.buffer):
            self._fill()
        return "" if self.position >= len(self.buffer) else self.buffer[self.position]

    def take(self) -> str:
        value = self.peek()
        if value:
            self.position += 1
            self.offset += 1
        return value

    def _fill(self) -> None:
        if self.eof:
            return
        if self.position:
            self.buffer = self.buffer[self.position:]
            self.position = 0
        try:
            chunk = self.source.read(self.chunk_size)
        except OSError as exc:
            raise PortableInputError(f"cannot read portable JSON: {exc}") from exc
        try:
            if chunk:
                self.buffer += self.decoder.decode(chunk, final=False)
            else:
                self.buffer += self.decoder.decode(b"", final=True)
                self.eof = True
        except UnicodeDecodeError as exc:
            raise PortableInputError(f"portable JSON is not valid UTF-8: {exc}") from exc


class _PortableJsonParser:
    def __init__(
        self,
        stream: _ChunkedText,
        workspace: PortableInputWorkspace,
        on_spooled: Callable[[str, int], None] | None,
    ) -> None:
        self.stream = stream
        self.workspace = workspace
        self.on_spooled = on_spooled

    def parse(self) -> Any:
        value = self._value(())
        self._whitespace()
        if self.stream.peek():
            self._fail("trailing data")
        return value

    def _value(self, path: tuple[str, ...]) -> Any:
        self._whitespace()
        character = self.stream.peek()
        if character == "{":
            return self._object(path)
        if character == "[":
            section = _SPOOL_PATHS.get(path)
            return self._spooled_array(section, path) if section else self._array(path)
        if character == '"':
            return self._string()
        if not character:
            self._fail("unexpected end of input")
        return self._scalar()

    def _object(self, path: tuple[str, ...]) -> dict[str, Any]:
        self._expect("{")
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._whitespace()
        if self.stream.peek() == "}":
            self.stream.take()
            return result
        while True:
            self._whitespace()
            if self.stream.peek() != '"':
                self._fail("object key must be a string")
            key = self._string()
            if key in seen:
                self._fail(f"duplicate object key {key!r}")
            seen.add(key)
            self._whitespace()
            self._expect(":")
            result[key] = self._value((*path, key))
            self._whitespace()
            delimiter = self.stream.take()
            if delimiter == "}":
                return result
            if delimiter != ",":
                self._fail("expected ',' or '}'")

    def _array(self, path: tuple[str, ...]) -> list[Any]:
        self._expect("[")
        result: list[Any] = []
        self._whitespace()
        if self.stream.peek() == "]":
            self.stream.take()
            return result
        while True:
            result.append(self._value((*path, str(len(result)))))
            self._whitespace()
            delimiter = self.stream.take()
            if delimiter == "]":
                return result
            if delimiter != ",":
                self._fail("expected ',' or ']'")

    def _spooled_array(self, section: str, path: tuple[str, ...]) -> SpoolMarker:
        self._expect("[")
        self._whitespace()
        if self.stream.peek() == "]":
            self.stream.take()
            return SpoolMarker(section)
        while True:
            value = self._value((*path, str(self.workspace.counts[section])))
            index = self.workspace.append(section, value)
            if self.on_spooled is not None:
                self.on_spooled(section, index)
            del value
            self._whitespace()
            delimiter = self.stream.take()
            if delimiter == "]":
                return SpoolMarker(section)
            if delimiter != ",":
                self._fail("expected ',' or ']'")

    def _string(self) -> str:
        raw = ['"']
        self._expect('"')
        escaped = False
        while True:
            character = self.stream.take()
            if not character:
                self._fail("unterminated string")
            raw.append(character)
            if character == '"' and not escaped:
                break
            if character == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        try:
            value = json.loads("".join(raw))
        except json.JSONDecodeError as exc:
            self._fail(f"invalid string: {exc.msg}")
        if not isinstance(value, str):
            self._fail("object key must decode as a string")
        return value

    def _scalar(self) -> Any:
        token: list[str] = []
        while (character := self.stream.peek()) and character not in " \t\r\n,]}":
            token.append(self.stream.take())
        try:
            value = json.loads("".join(token))
        except json.JSONDecodeError as exc:
            self._fail(f"invalid value: {exc.msg}")
        if isinstance(value, (dict, list, str)):
            self._fail("invalid scalar")
        return value

    def _whitespace(self) -> None:
        while (character := self.stream.peek()) and character in " \t\r\n":
            self.stream.take()

    def _expect(self, expected: str) -> None:
        if self.stream.take() != expected:
            self._fail(f"expected {expected!r}")

    def _fail(self, detail: str) -> None:
        raise PortableInputError(
            f"invalid portable JSON near character {self.stream.offset}: {detail}"
        )


@contextmanager
def read_portable_workspace(
    source: str | Path,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    workspace_parent: str | Path | None = None,
    _open_binary: Callable[[Path], BinaryIO] | None = None,
    _on_spooled: Callable[[str, int], None] | None = None,
) -> Iterator[PortableInputWorkspace]:
    """Parse portable JSON into bounded disk spools for later validation passes."""
    path = Path(source).expanduser().resolve()
    opener = _open_binary or (lambda candidate: candidate.open("rb"))
    parent = None if workspace_parent is None else str(Path(workspace_parent))
    with tempfile.TemporaryDirectory(prefix="ah-portable-input-", dir=parent) as directory:
        workspace = PortableInputWorkspace(Path(directory))
        try:
            try:
                with opener(path) as binary:
                    parser = _PortableJsonParser(
                        _ChunkedText(binary, chunk_size), workspace, _on_spooled
                    )
                    workspace.structure = parser.parse()
            except PortableInputError:
                raise
            except OSError as exc:
                raise PortableInputError(f"cannot read portable JSON {path}: {exc}") from exc
            finally:
                workspace.finish()
            yield workspace
        finally:
            workspace.finish()
