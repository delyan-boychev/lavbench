"""Child-process Parquet checks: run only under utils.limited_process, never in the web process."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.ipc as ipc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

ID_COLUMNS = ("id", "query_id", "doc_id")
# Bytes per value besides string content: the offsets and a little encoding overhead
STRING_OVERHEAD = 4
NUMBER_WIDTH = 8
# Page headers, levels and statistics on top of an honest file's plain-encoded ids
ID_BYTES_SLACK = 64 * 1024


class RefusedError(Exception):
    """The file cannot be scored; the message is safe to show the competitor."""

    def __init__(self, message: str, counts: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.counts = counts or {}


def kind(arrow_type: Any) -> str | None:
    """The comparable family of an id type, or None for types ids may not have."""
    if pa.types.is_dictionary(arrow_type):
        arrow_type = arrow_type.value_type
    if pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type):
        return "number"
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_timestamp(arrow_type) or pa.types.is_date(arrow_type):
        return "time"
    return None


def comparable(array: Any) -> Any:
    if pa.types.is_dictionary(array.type):
        array = array.dictionary_decode()
    found = kind(array.type)
    if found == "number":
        return pc.cast(array, pa.float64())
    if found == "string":
        return pc.cast(array, pa.large_string())
    return array


def longest(array: Any) -> int:
    """Byte length of the longest string, read from the dictionary when there is one."""
    values = array.dictionary if pa.types.is_dictionary(array.type) else array
    if len(values) == 0:
        return 0
    return int(pc.max(pc.binary_length(values)).as_py() or 0)


def id_columns(names: list[str]) -> list[str]:
    return ["query_id", "doc_id"] if "query_id" in names else ["id"]


def write_atomically(path: str, write: Any) -> None:
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    os.close(handle)
    try:
        write(temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_labels(config: dict[str, Any]) -> dict[str, Any]:
    """Read the labels once: their columns, id statistics and the id set for later checks."""
    try:
        parquet = pq.ParquetFile(config["labels_path"])
    except pa.ArrowException as exc:
        raise RefusedError("labels.parquet cannot be read.") from exc
    names = list(parquet.schema_arrow.names)
    columns = id_columns(names)
    if any(name not in names for name in columns):
        return {"columns": names}
    for name in columns:
        if kind(parquet.schema_arrow.field(name).type) is None:
            raise RefusedError(f"The labels column {name} does not hold plain ids.")
    table = parquet.read(columns=columns)
    key = table.column(columns[0]).combine_chunks()
    retrieval = len(columns) > 1
    if retrieval:
        # Labels repeat a query for each relevant document
        key = pc.unique(key)
    elif pc.count_distinct(key).as_py() != len(key):
        raise RefusedError("labels.parquet has duplicate ids.")
    stats: dict[str, Any] = {
        "format": config["cache_format"],
        "retrieval": retrieval,
        "ids": len(key),
        "kind": kind(key.type),
        "longest": longest(key) if kind(key.type) == "string" else None,
    }
    width = (
        (stats["longest"] or 0) + STRING_OVERHEAD
        if stats["longest"] is not None
        else (NUMBER_WIDTH)
    )
    stats["id_bytes"] = stats["ids"] * width
    cache = config["cache_path"]
    write_atomically(
        cache,
        lambda path: _write_ids(path, columns[0], key),
    )
    write_atomically(
        os.path.splitext(cache)[0] + ".json",
        lambda path: _write_json(path, stats),
    )
    return {"columns": names, "stats": stats}


def _write_ids(path: str, name: str, ids: Any) -> None:
    table = pa.table({name: ids})
    with pa.OSFile(path, "wb") as sink, ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)


def _write_json(path: str, value: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def _footer(parquet: Any, path: str, limits: dict[str, int]) -> None:
    metadata = parquet.metadata
    uncompressed = sum(
        metadata.row_group(group).column(column).total_uncompressed_size
        for group in range(metadata.num_row_groups)
        for column in range(metadata.row_group(group).num_columns)
    )
    if (
        os.path.getsize(path) > limits["max_file_bytes"]
        or metadata.num_rows > limits["max_rows"]
        or metadata.num_columns > limits["max_columns"]
        or uncompressed > limits["max_uncompressed_bytes"]
    ):
        raise RefusedError("It exceeds the size limits.")


def _column_bytes(parquet: Any, name: str) -> int:
    metadata = parquet.metadata
    index = parquet.schema_arrow.names.index(name)
    return sum(
        metadata.row_group(group).column(index).total_uncompressed_size
        for group in range(metadata.num_row_groups)
    )


def _cheap_checks(parquet: Any, path: str, columns: list[str], stats: dict[str, Any]) -> None:
    """Bounds from the labels, checked before anything can expand."""
    rows = parquet.metadata.num_rows
    key = columns[0]
    if not stats["retrieval"]:
        if rows != stats["ids"]:
            raise RefusedError(f"The file has {rows} rows; the task has {stats['ids']} ids.")
        bound = stats["id_bytes"] + stats["id_bytes"] // 8 + ID_BYTES_SLACK
        if _column_bytes(parquet, key) > bound:
            raise RefusedError("The id column is far larger than the task's ids.")
    if stats["longest"] is not None:
        values = pq.read_table(path, columns=[key], read_dictionary=[key]).column(key)
        if max((longest(chunk) for chunk in values.chunks), default=0) > stats["longest"]:
            raise RefusedError(f"The column {key} has ids longer than any id of the task.")
    if not stats["retrieval"]:
        values = pq.read_table(path, columns=[key]).column(key).combine_chunks()
        duplicates = rows - pc.count_distinct(comparable(values)).as_py()
        if duplicates:
            raise RefusedError(f"{duplicates} ids appear more than once.")


def _read_bounded(parquet: Any, columns: list[str], limits: dict[str, int]) -> Any:
    """Read every column in small batches under the decoded-bytes cap; keep only the ids."""
    kept: list[Any] = []
    decoded = 0
    for batch in parquet.iter_batches(batch_size=limits["batch_rows"]):
        decoded += batch.nbytes
        if decoded > limits["max_decoded_bytes"]:
            raise RefusedError("The file decodes to more than the size limit.")
        kept.append(batch.select(columns))
    schema = pa.schema([parquet.schema_arrow.field(name) for name in columns])
    return pa.Table.from_batches(kept, schema=schema)


def _load_labels(config: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """The cached label stats and ids; the web process rebuilds them before a check."""
    with open(os.path.splitext(config["cache_path"])[0] + ".json", encoding="utf-8") as handle:
        stats: dict[str, Any] = json.load(handle)
    if stats.get("format") != config["cache_format"]:
        raise RuntimeError("The label cache has another format")
    with pa.memory_map(config["cache_path"]) as source:
        expected = comparable(ipc.open_file(source).read_all().column(0).combine_chunks())
    return stats, expected


def check_submission(config: dict[str, Any]) -> None:
    stats, expected = _load_labels(config)
    try:
        _check_file(config, stats, expected)
    except pa.ArrowException as exc:
        # Arrow failing on the submitted bytes is the file's fault, not the platform's
        raise RefusedError("The file cannot be read as Parquet.") from exc


def _check_file(config: dict[str, Any], stats: dict[str, Any], expected: Any) -> None:
    path = config["sub_path"]
    limits = config["limits"]
    parquet = pq.ParquetFile(path)
    _footer(parquet, path, limits)
    names = list(parquet.schema_arrow.names)
    columns = ["query_id", "doc_id"] if stats["retrieval"] else ["id"]
    required = config["required_columns"]
    missing = [name for name in (*columns, *required) if name not in names]
    if missing:
        raise RefusedError(f"The column(s) {', '.join(missing)} are missing.")
    if not required and not any(name not in ID_COLUMNS for name in names):
        raise RefusedError("There is no prediction column next to the ids.")
    for name in columns:
        if kind(parquet.schema_arrow.field(name).type) is None:
            raise RefusedError(f"The column {name} holds values that are not plain ids.")
    if kind(parquet.schema_arrow.field(columns[0]).type) != stats["kind"]:
        raise RefusedError("The ids have another type than the task's ids.")
    _cheap_checks(parquet, path, columns, stats)
    table = _read_bounded(parquet, columns, limits)
    for name in columns:
        empty = pc.sum(pc.is_null(table.column(name), nan_is_null=True)).as_py() or 0
        if empty:
            raise RefusedError(f"The column {name} has {empty} empty values.")
    if stats["retrieval"]:
        distinct = table.group_by(columns).aggregate([]).num_rows
        if distinct != table.num_rows:
            raise RefusedError(f"{table.num_rows - distinct} ids appear more than once.")
    submitted = comparable(table.column(columns[0]).combine_chunks())
    if stats["retrieval"]:
        submitted = pc.unique(submitted)
    missing_ids = len(expected) - (pc.sum(pc.is_in(expected, value_set=submitted)).as_py() or 0)
    unexpected = len(submitted) - (pc.sum(pc.is_in(submitted, value_set=expected)).as_py() or 0)
    if missing_ids or unexpected:
        raise RefusedError(
            f"{missing_ids} of the {len(expected)} expected ids are missing "
            f"and {unexpected} ids are not in the task.",
            {
                "expected_ids": len(expected),
                "missing_ids": missing_ids,
                "unexpected_ids": unexpected,
            },
        )


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as handle:
        config = json.load(handle)
    result: dict[str, Any] = {"problem": None, "counts": {}}
    try:
        if config["mode"] == "labels":
            result.update(build_labels(config))
        else:
            check_submission(config)
    except RefusedError as exc:
        result.update(problem=str(exc), counts=exc.counts)
    except MemoryError:
        # The memory limit fits the labels, so running out is the file's fault
        result.update(problem="The file is too large to check.", counts={})
    _write_json(config["result_path"], result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
