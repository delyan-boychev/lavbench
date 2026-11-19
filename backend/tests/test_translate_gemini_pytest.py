"""Tests for the block-level Markdown planning and the API calls of scripts/translate_gemini.py."""

# ruff: noqa: RUF001

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "translate_gemini.py"
DOC_DIRS = ("guides", "docs/source")

# Prose stand-ins for translations; code spans, link targets, fence lines and heading marks stay
_PROTECT = re.compile(r"(`[^`\n]*`|\]\([^)]*\)|^[ \t]*(?:`{3,}|~{3,}).*$|https?://\S+)", re.M)


def swap(text, old="e", new="е"):
    parts = _PROTECT.split(text)
    return "".join(p if i % 2 else p.replace(old, new) for i, p in enumerate(parts))


def model_bg(text):
    return swap(text, "o", "о")


def _load():
    spec = importlib.util.spec_from_file_location("translate_gemini", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tg(monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "ui_labels", lambda text: "(none)")
    monkeypatch.setattr(module, "SLEEP_BETWEEN_CALLS", 0)
    monkeypatch.setattr(module, "RETRY_BASE_SECONDS", 0)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return module


def kinds(tg, text):
    return [b.kind for b in tg.split_blocks(text)]


def units(groups, tg):
    return tg._units_of(groups)


SAMPLE = """# Guide

Intro paragraph that is long enough
to wrap over two lines.

## Setup

1. First step with a
   wrapped line.
2. Second step.
10. Tenth step.

- Bullet one
  - Nested bullet
* Star bullet
+ Plus bullet

**Bold start** is a paragraph.
*Italic start* too.

```bash
echo "# not a heading"

- not an item
```

| Name | Value |
|------|-------|
| a    | 1     |

> A quote
> over two lines.

<!-- a comment

# not a heading
-->

---

Setext title
============

    indented code

## Links

See [the docs](https://example.com/docs) and [below](#links).
"""

SAMPLE_KINDS = [
    "h1",
    "para",
    "h2",
    "ol",
    "ol",
    "ol",
    "ul",
    "ul",
    "ul",
    "ul",
    "para",
    "fence",
    "row",
    "row-sep",
    "row",
    "quote",
    "html",
    "hr",
    "setext1",
    "para",
    "h2",
    "para",
]


# ── Lossless tokenizer ──


def _repository_documents():
    return [p for d in DOC_DIRS for p in sorted((ROOT / d).rglob("*.md")) if p.is_file()]


def test_repository_documents_are_found():
    assert _repository_documents()


@pytest.mark.parametrize("path", _repository_documents(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_repository_document_splits_losslessly(tg, path):
    text = path.read_text(encoding="utf-8")
    assert "".join(b.full for b in tg.split_blocks(text)) == text
    assert "".join(tg.split_sections(text)) == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n",
        "no final newline",
        "  \n\ntext after blank lines\n",
        "a\r\nb\r\n\r\n- c\r\n- d\r\n",
        SAMPLE,
        SAMPLE.rstrip("\n"),
        SAMPLE + "\n\n  \n",
        "---\ntitle: x\n# comment\n---\n# Heading\n",
        "```\nunclosed fence\n# not a heading\n",
        "line with trailing spaces   \n\nnext  \n",
        "text with a line separator\n",
    ],
)
def test_round_trip(tg, text):
    assert "".join(b.full for b in tg.split_blocks(text)) == text
    assert "".join(tg.split_sections(text)) == text


def test_sample_block_kinds(tg):
    assert kinds(tg, SAMPLE) == SAMPLE_KINDS


def test_tilde_and_longer_fences_hide_inner_fences_and_headings(tg):
    text = "````md\n```\n# inner\n```\n````\n\n~~~\n# x\n\n~~~\n\n## Real\n"
    assert kinds(tg, text) == ["fence", "fence", "h2"]
    assert len(tg.split_sections(text)) == 2


def test_fence_inside_a_list_item_belongs_to_the_item(tg):
    text = "1. Run:\n   ```bash\n   make\n\n   ```\n2. Next\n"
    blocks = tg.split_blocks(text)
    assert [b.kind for b in blocks] == ["ol", "ol"]
    assert "make" in blocks[0].text


def test_myst_directive_and_mermaid_fences(tg):
    text = "```{note}\nA note.\n\n- inside\n```\n\n```mermaid\ngraph TD\n```\n"
    assert kinds(tg, text) == ["fence", "fence"]
    assert tg._fences(tg.split_blocks(text)[0]) == [("```", "{note}"), ("```", "")]


def test_inline_triple_backticks_are_not_a_fence(tg):
    assert kinds(tg, "```code``` in a line\n\n# H\n") == ["para", "h1"]


def test_lazy_continuation_and_numbers_in_wrapped_lines(tg):
    assert kinds(tg, "- item\nwrapped line\n- next\n") == ["ul", "ul"]
    assert kinds(tg, "A paragraph that wraps at\n10. a number stays in it\n") == ["para"]
    assert kinds(tg, "A paragraph\n1. starts a list\n") == ["para", "ol"]
    assert kinds(tg, "1) one\n2) two\n") == ["ol", "ol"]


def test_bold_and_italic_line_starts_are_not_list_items(tg):
    assert kinds(tg, "**Bold** text\n*italic* text\n") == ["para"]


def test_html_comment_with_blank_lines_is_one_block(tg):
    text = "<!--\n\n- x\n# y\n\n-->\n\nText\n"
    assert kinds(tg, text) == ["html", "para"]


def test_horizontal_rule_and_setext_heading(tg):
    assert kinds(tg, "Text\n\n---\n\nTitle\n-----\n") == ["para", "hr", "setext2"]
    assert kinds(tg, "* * *\n") == ["hr"]


def test_front_matter_is_one_block(tg):
    blocks = tg.split_blocks("---\ntitle: x\n# comment\n---\n# Heading\n")
    assert [b.kind for b in blocks] == ["front", "h1"]


def test_heading_and_table_row_are_blocks_of_their_own_line(tg):
    assert kinds(tg, "# H\nText right after\n| a |\nnot a row\n") == ["h1", "para", "row", "para"]


def test_crlf_blocks_keep_their_line_ends(tg):
    blocks = tg.split_blocks("a\r\nb\r\n\r\nc\r\n")
    assert [(b.text, b.eol, b.sep) for b in blocks] == [
        ("a\r\nb", "\r\n", "\r\n"),
        ("c", "\r\n", ""),
    ]


# ── Block-level planning ──


def plan(tg, old, new, bg=None):
    bg = swap(old) if bg is None else bg
    groups = tg.plan_document(old, new, bg)
    assert groups is not None
    return groups


def fill(tg, groups):
    """Translate every unit with the stand-in model and render."""
    for unit in units(groups, tg):
        out, why = tg.fit_reply(unit["_blocks"], model_bg(unit["en"]))
        assert out is not None, why
        unit["_out"] = out
    return tg.render(groups)


BASE = """# Title

First paragraph.

## Part A

Alpha one.

Alpha two.

Alpha three.

## Part B

Beta one.

Beta two.
"""


def test_unchanged_document_has_no_units(tg):
    groups = plan(tg, BASE, BASE)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(BASE)


def test_reflow_and_trailing_spaces_are_no_change(tg):
    new = BASE.replace("Alpha one.", "Alpha\none.   ").replace("Beta two.\n", "Beta two.\n\n\n")
    groups = plan(tg, BASE, new)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(BASE) + "\n\n"


def test_changed_paragraph_sends_only_that_block(tg):
    new = BASE.replace("Alpha two.", "Alpha two, changed.")
    groups = plan(tg, BASE, new)
    [unit] = units(groups, tg)
    assert unit["_kind"] == "block"
    assert (unit["en"], unit["old_en"], unit["bg"]) == (
        "Alpha two, changed.",
        "Alpha two.",
        swap("Alpha two."),
    )
    assert unit["section"] == "## Part A"
    assert "bg_context" not in unit
    assert fill(tg, groups) == swap(BASE).replace(
        swap("Alpha two."), model_bg("Alpha two, changed.")
    )


def test_deleted_blocks_need_no_call(tg):
    new = BASE.replace("Alpha two.\n\n", "").replace("\n## Part B\n\nBeta one.\n\nBeta two.\n", "")
    groups = plan(tg, BASE, new)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(new)


def test_insert_at_section_start_and_end_carries_context(tg):
    new = BASE.replace("## Part A\n\n", "## Part A\n\nNew first.\n\n").replace(
        "Beta two.\n", "Beta two.\n\nNew last.\n"
    )
    groups = plan(tg, BASE, new)
    first, last = units(groups, tg)
    assert first["_kind"] == last["_kind"] == "insert"
    assert (first["en"], first["section"]) == ("New first.", "## Part A")
    assert first["bg_context"] == swap("## Part A")
    assert (last["en"], last["section"]) == ("New last.", "## Part B")
    assert last["bg_context"] == swap("Beta two.")
    assert set(first) - {"_kind", "_blocks"} == {"en", "section", "bg_context"}
    assert fill(tg, groups) == swap(BASE).replace(
        "## Part A\n\n", "## Part A\n\n" + model_bg("New first.") + "\n\n"
    ).replace(swap("Beta two.\n"), swap("Beta two.\n") + "\n" + model_bg("New last.") + "\n")


def test_neighbour_context_is_truncated(tg):
    long = "Long " * 200
    old = f"# T\n\n{long}\n"
    groups = plan(tg, old, old + "\nAdded.\n")
    [unit] = units(groups, tg)
    assert len(unit["bg_context"]) == tg.NEIGHBOUR_CONTEXT_CHARS


def test_moved_and_duplicated_blocks_reuse_their_bulgarian(tg):
    moved = BASE.replace("Alpha one.\n\n", "").replace("Beta one.", "Alpha one.\n\nBeta one.")
    groups = plan(tg, BASE, moved)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(moved)
    duplicated = BASE.replace("Beta two.", "Beta two.\n\nAlpha three.")
    groups = plan(tg, BASE, duplicated)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(duplicated)


def test_ambiguous_known_block_is_translated(tg):
    old = "# T\n\nSame.\n\n## U\n\nSame.\n"
    bg = "# T\n\nOne.\n\n## U\n\nTwo.\n"
    groups = tg.plan_document(old, old + "\nSame.\n", bg)
    [unit] = units(groups, tg)
    assert unit["en"] == "Same."


def test_n_to_m_replacement_is_one_unit(tg):
    new = BASE.replace("Alpha one.\n\nAlpha two.", "Gamma one.\n\nGamma two.\n\nGamma three.")
    groups = plan(tg, BASE, new)
    [unit] = units(groups, tg)
    assert unit["en"] == "Gamma one.\n\nGamma two.\n\nGamma three."
    assert unit["old_en"] == "Alpha one.\n\nAlpha two."
    assert len(unit["_blocks"]) == 3
    assert fill(tg, groups) == swap(BASE).replace(
        swap("Alpha one.\n\nAlpha two."), model_bg("Gamma one.\n\nGamma two.\n\nGamma three.")
    )


def test_changed_heading_same_and_different_level(tg):
    groups = plan(tg, BASE, BASE.replace("## Part B", "## Part Bee"))
    [unit] = units(groups, tg)
    assert unit["en"] == "## Part Bee"
    assert "section" not in unit
    groups = plan(tg, BASE, BASE.replace("## Part B", "### Part B"))
    [unit] = units(groups, tg)
    assert unit["en"] == "### Part B"
    assert fill(tg, groups).count("### Part B") == 1


TABLE = "# T\n\n| Name | Value |\n|------|-------|\n| a | 1 |\n| b | 2 |\n"


def test_table_changed_cell_and_added_row(tg):
    groups = plan(tg, TABLE, TABLE.replace("| b | 2 |", "| b | 3 |"))
    [unit] = units(groups, tg)
    assert unit["en"] == "| b | 3 |"
    groups = plan(tg, TABLE, TABLE + "| c | 4 |\n")
    [unit] = units(groups, tg)
    assert (unit["_kind"], unit["en"]) == ("insert", "| c | 4 |")


def test_table_added_column_is_one_unit(tg):
    new = "# T\n\n| Name | Value | Note |\n|------|-------|------|\n| a | 1 | x |\n| b | 2 | y |\n"
    groups = plan(tg, TABLE, new)
    [unit] = units(groups, tg)
    assert len(unit["_blocks"]) == 4
    assert tg.fit_reply(unit["_blocks"], model_bg(unit["en"]))[0] is not None
    dropped = unit["en"].replace(" Note |", "")
    assert tg.fit_reply(unit["_blocks"], dropped)[0] is None


def test_whole_new_and_deleted_section(tg):
    new = BASE.replace("## Part B", "## Part C\n\nGamma.\n\n## Part B")
    groups = plan(tg, BASE, new)
    [unit] = units(groups, tg)
    assert unit["_kind"] == "insert"
    assert unit["en"] == "## Part C\n\nGamma."
    assert unit["bg_context"] == swap("Alpha three.")
    gone = BASE[: BASE.index("## Part B")]
    groups = plan(tg, BASE, gone)
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(gone)


def test_section_with_an_extra_bulgarian_block_falls_back_to_that_section(tg):
    bg = swap(BASE).replace(swap("Alpha three."), swap("Alpha three.") + "\n\nExtra.")
    new = BASE.replace("Alpha two.", "Alpha 2.").replace("Beta two.", "Beta 2.")
    groups = tg.plan_document(BASE, new, bg)
    first, second = units(groups, tg)
    assert first["_kind"] == "section"
    assert first["en"].startswith("## Part A") and first["bg"].endswith("Extra.")
    assert (second["_kind"], second["en"]) == ("block", "Beta 2.")


def test_misaligned_sections_return_none(tg):
    assert tg.plan_document(BASE, BASE + "\nMore.\n", "# Only one section\n") is None


def test_final_newline_change_keeps_bulgarian(tg):
    groups = plan(tg, BASE, BASE.rstrip("\n"))
    assert units(groups, tg) == []
    assert tg.render(groups) == swap(BASE).rstrip("\n")


def test_crlf_document(tg):
    old = BASE.replace("\n", "\r\n")
    new = old.replace("Alpha two.", "Alpha two, changed.")
    groups = plan(tg, old, new)
    [unit] = units(groups, tg)
    out, why = tg.fit_reply(unit["_blocks"], "Alpha two, chаnged.\n")
    assert out is not None, why
    unit["_out"] = out
    result = tg.render(groups)
    assert result == swap(old).replace(swap("Alpha two."), "Alpha two, chаnged.")
    assert "\n" not in result.replace("\r\n", "")


def test_reply_indentation_is_restored(tg):
    blocks = tg.split_blocks("  - Nested item\n")
    out, _ = tg.fit_reply(blocks, "- Вложен елемент")
    assert out == "  - Вложен елемент\n"


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("Първи и втори.", "block(s) instead of"),
        ("Първи.\n\nВтори.\n\n### Заглавие", "kind"),
        ("Първи.\n\nВтори [връзка](https://other.example).", "link targets"),
    ],
)
def test_bad_replies_are_rejected(tg, reply, reason):
    blocks = tg.split_blocks("First.\n\nSecond [link](https://example.com).\n")
    if reason == "kind":
        blocks = tg.split_blocks("First.\n\nSecond.\n\n## Heading\n")
    out, why = tg.fit_reply(blocks, reply)
    assert out is None
    assert reason in why


def test_dropped_fence_is_rejected(tg):
    blocks = tg.split_blocks("Run:\n```bash\nmake\n```\n")
    assert tg.fit_reply(blocks, "Изпълнете:\nmake")[0] is None
    assert tg.fit_reply(blocks, "Изпълнете:\n```bash\nmake\n```")[0] is not None


def test_anchor_links_may_change_but_not_their_number(tg):
    blocks = tg.split_blocks("See [below](#links).\n")
    assert tg.fit_reply(blocks, "Вижте [по-долу](#връзки).")[0] is not None
    assert tg.fit_reply(blocks, "Вижте по-долу.")[0] is None


# ── Whole documents with a stand-in model ──


class FakeModel:
    """Stand-in for gemini_call: records prompts and answers from a list of reply makers."""

    def __init__(self, *makers):
        self.makers = list(makers)
        self.prompts = []

    def __call__(self, model, prompt, system=None, json_mode=False):
        self.prompts.append(prompt)
        maker = self.makers.pop(0) if self.makers else good_reply
        return maker(prompt)

    def payload(self, n=0):
        return json.loads(self.prompts[n].rsplit("\nJSON:\n", 1)[1])


def good_reply(prompt):
    if "\nJSON:\n" not in prompt:
        return model_bg(prompt.rsplit("DOCUMENT:\n", 1)[1])
    payload = json.loads(prompt.rsplit("\nJSON:\n", 1)[1])
    return json.dumps({k: model_bg(v["en"]) for k, v in payload.items()}, ensure_ascii=False)


def broken(change):
    def make(prompt):
        payload = json.loads(prompt.rsplit("\nJSON:\n", 1)[1])
        return json.dumps({k: change(model_bg(v["en"])) for k, v in payload.items()})

    return make


@pytest.fixture
def document(tg, tmp_path, monkeypatch):
    """Write a document pair and fake git; returns a runner for translate_document."""

    def setup(old_en, new_en, committed_bg, current_bg=None, *makers, force=False, dry_run=False):
        src, out = tmp_path / "en.md", tmp_path / "bg.md"
        src.write_text(new_en, encoding="utf-8")
        if current_bg is not None or committed_bg is not None:
            out.write_text(current_bg if current_bg is not None else committed_bg, encoding="utf-8")
        history = {src: old_en, out: committed_bg}
        monkeypatch.setattr(tg, "at_last_translation", lambda path, _out: history[path])
        fake = FakeModel(*makers)
        monkeypatch.setattr(tg, "gemini_call", fake)
        tg.translate_document("m", src, out, "en.md", dry_run=dry_run, force=force)
        return fake, out.read_text(encoding="utf-8") if out.exists() else None

    return setup


LINKED = """# Title

Intro with a [link](https://example.com) and a [jump](#part-a).

## Part A

Alpha one.

```bash
make test
```

Alpha two.
"""


def test_document_good_reply_is_merged_in_one_call(tg, document):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.")
    fake, result = document(LINKED, new, swap(LINKED))
    assert len(fake.prompts) == 1
    assert list(fake.payload().values()) == [
        {
            "en": "Alpha two, changed.",
            "old_en": "Alpha two.",
            "bg": swap("Alpha two."),
            "section": "## Part A",
        }
    ]
    assert "paragraphs, list items, table rows" in fake.prompts[0]
    assert result == swap(LINKED).replace(swap("Alpha two."), model_bg("Alpha two, changed."))


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text.replace("\n\n", " "),
        lambda text: text.replace("```bash\n", "").replace("\n```", ""),
        lambda text: text.replace("## ", "### "),
        lambda text: text.replace("https://example.com", "https://elsewhere.example"),
    ],
    ids=["merged paragraphs", "dropped fence", "heading level", "link target"],
)
def test_bad_reply_is_retried_as_whole_sections(tg, document, change):
    new = LINKED.replace("Intro with", "Intro, changed, with").replace(
        "Alpha one.", "## Part A2\n\nAlpha one, changed.\n\n```bash\nmake lint\n```"
    )
    fake, result = document(LINKED, new, swap(LINKED), None, broken(change), good_reply)
    assert len(fake.prompts) == 2
    retried = list(fake.payload(1).values())
    assert all(unit["en"].startswith("#") for unit in retried)
    assert result is not None and "Part A2" in result
    assert result.count("```") == 4


def test_both_bad_replies_leave_the_file_unchanged(tg, document, capsys):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.")
    bad = broken(lambda text: text + "\n\n## Extra")
    fake, result = document(LINKED, new, swap(LINKED), None, bad, bad)
    assert len(fake.prompts) == 2
    assert result == swap(LINKED)
    assert "left unchanged" in capsys.readouterr().out


def test_invalid_json_is_retried(tg, document):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.")
    fake, result = document(LINKED, new, swap(LINKED), None, lambda prompt: "not json")
    assert len(fake.prompts) == 2
    assert model_bg("Alpha two, changed.") in result


def test_no_previous_translation_translates_the_whole_file(tg, document):
    fake, result = document(None, LINKED, None)
    assert len(fake.prompts) == 1
    assert "DOCUMENT:\n" in fake.prompts[0]
    assert result.startswith(model_bg("# Title"))


def test_force_translates_the_whole_file(tg, document):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.")
    fake, _ = document(LINKED, new, swap(LINKED), None, force=True)
    assert len(fake.prompts) == 1
    assert "DOCUMENT:\n" in fake.prompts[0]


def test_unchanged_document_is_skipped(tg, document, capsys):
    fake, result = document(LINKED, LINKED, swap(LINKED), "current")
    assert fake.prompts == []
    assert result == "current"
    assert "skip" in capsys.readouterr().out


def test_reflow_only_writes_the_kept_bulgarian_without_a_call(tg, document):
    new = LINKED.replace("Intro with a", "Intro with\na")
    fake, result = document(LINKED, new, swap(LINKED))
    assert fake.prompts == []
    assert result == swap(LINKED)


def test_second_run_plans_against_the_committed_bulgarian(tg, document):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.")
    earlier_run = swap(LINKED).replace(swap("Alpha two."), "uncommitted")
    fake, result = document(LINKED, new, swap(LINKED), earlier_run)
    assert next(iter(fake.payload().values()))["bg"] == swap("Alpha two.")
    assert "uncommitted" not in result


def test_anchors_are_relinked_to_translated_headings(tg, document):
    old = "# Title\n\nGo to [part](#part-a).\n\n## Part A\n\nText.\n"
    bg = "# Заглавие\n\nКъм [част](#част-а).\n\n## Част А\n\nТекст.\n"
    new = old.replace("## Part A", "## Part Alpha").replace("(#part-a)", "(#part-alpha)")
    replies = {
        "Go to [part](#part-alpha).": "Към [част](#part-alpha).",
        "## Part Alpha": "## Част Алфа",
    }

    def reply(prompt):
        payload = json.loads(prompt.rsplit("\nJSON:\n", 1)[1])
        return json.dumps({k: replies[v["en"]] for k, v in payload.items()}, ensure_ascii=False)

    fake, result = document(old, new, bg, None, reply)
    assert len(fake.prompts) == 1
    assert result == "# Заглавие\n\nКъм [част](#част-алфа).\n\n## Част Алфа\n\nТекст.\n"


def test_dry_run_lists_units_and_estimate_without_calls(tg, document, capsys):
    new = LINKED.replace("Alpha two.", "Alpha two, changed.").replace(
        "## Part A\n\n", "## Part A\n\nNew paragraph.\n\n"
    )
    fake, result = document(LINKED, new, swap(LINKED), dry_run=True)
    out = capsys.readouterr().out
    assert fake.prompts == []
    assert result == swap(LINKED)
    assert "2 unit(s)" in out
    assert "block   ## Part A" in out and "insert  ## Part A" in out
    assert "(estimate)" in out
    assert tg.ESTIMATE["calls"] == 1


# ── Token estimate, cap and API calls ──


def test_estimate_uses_the_named_constants(tg):
    tokens_in, tokens_out = tg.estimate_tokens("x" * 300, 600)
    assert tokens_in == -(-(len(tg.SYSTEM_PROMPT) + 300) // tg.CHARS_PER_TOKEN)
    assert tokens_out == -(-600 // tg.CHARS_PER_TOKEN) + tg.THINKING_TOKENS_PER_CALL


def test_call_over_max_tokens_is_refused(tg, monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(tg, "gemini_call", fake)
    monkeypatch.setattr(tg, "MAX_TOKENS", 100)
    with pytest.raises(RuntimeError, match="max-tokens"):
        tg.call_model("m", "prompt", 10)
    assert fake.prompts == []


def test_run_estimated_over_max_tokens_makes_no_call(tg, monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(tg, "gemini_call", fake)
    monkeypatch.setattr(tg, "load_api_key", lambda *a: pytest.fail("the key was loaded"))

    def run_targets(args, dry_run):
        tg.plan_call("x" * 3000, 3000)
        if not dry_run:
            tg.call_model(args.model, "x" * 3000, 3000)

    monkeypatch.setattr(tg, "run_targets", run_targets)
    monkeypatch.setattr(sys, "argv", ["translate_gemini.py", "--max-tokens", "10"])
    with pytest.raises(SystemExit, match="exceed --max-tokens 10"):
        tg.main()
    assert fake.prompts == []


class FakeInteractions:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def interaction(text):
    usage = SimpleNamespace(
        total_input_tokens=10, total_cached_tokens=2, total_output_tokens=5, total_thought_tokens=3
    )
    return SimpleNamespace(output_text=text, usage=usage)


def test_gemini_call_sends_a_stateless_interaction(tg, monkeypatch):
    fake = FakeInteractions(interaction(" {} "))
    monkeypatch.setattr(tg, "_client", lambda: SimpleNamespace(interactions=fake))
    monkeypatch.setattr(tg, "FLEX", True)
    assert tg.gemini_call("gemini-x", "prompt", system="sys", json_mode=True) == "{}"
    assert fake.requests == [
        {
            "model": "gemini-x",
            "input": "prompt",
            "store": False,
            "generation_config": {"thinking_level": "low"},
            "system_instruction": "sys",
            "response_format": {"type": "text", "mime_type": "application/json"},
            "service_tier": "flex",
        }
    ]
    assert tg.USAGE == {"calls": 1, "input": 10, "cached": 2, "output": 5, "thoughts": 3}


def test_flash_lite_uses_minimal_thinking(tg):
    assert tg.thinking_level("gemini-3.5-flash-lite") == "minimal"
    assert tg.thinking_level("gemini-4-carbon") == "low"


def test_busy_api_is_retried_but_other_errors_are_not(tg, monkeypatch):
    errors = pytest.importorskip("google.genai.errors")
    busy = errors.APIError(429, {"error": {"message": "busy", "status": "RESOURCE_EXHAUSTED"}})
    fake = FakeInteractions(busy, interaction("ok"))
    monkeypatch.setattr(tg, "_client", lambda: SimpleNamespace(interactions=fake))
    assert tg.gemini_call("m", "p") == "ok"
    assert len(fake.requests) == 2
    bad = errors.APIError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})
    fake = FakeInteractions(bad, interaction("never"))
    monkeypatch.setattr(tg, "_client", lambda: SimpleNamespace(interactions=fake))
    with pytest.raises(RuntimeError, match="400"):
        tg.gemini_call("m", "p")
    assert len(fake.requests) == 1


def test_script_imports_without_the_sdk_or_a_key(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.genai", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    module = _load()
    assert module._CLIENT is None
