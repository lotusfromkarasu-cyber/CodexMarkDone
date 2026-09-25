import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "codex_markdone.py"
SPEC = importlib.util.spec_from_file_location("codex_markdone", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class TestCodexMarkDone(unittest.TestCase):
    def test_fraction_mathml(self):
        result = MODULE.latex_to_mathml(r"A_{0,H_z}=\frac{x}{y}")
        self.assertTrue(result.startswith('<math xmlns="http://www.w3.org/1998/Math/MathML"'))
        self.assertIn("<mfrac>", result)
        self.assertNotIn("<msubsup>", result)
        self.assertTrue(all(part in result for part in ("A", "x", "y")))


    def test_delimiter_normalization_only(self):
        source = r"code `\\(` and \\[x^2\\] plus \\(y\\) and C:\\temp\\file"
        normalized = MODULE.normalize_markdown(source)
        self.assertIn("`\\\\(`", normalized)
        self.assertIn("$$x^2$$", normalized)
        self.assertIn("$y$", normalized)
        self.assertIn(r"C:\\temp\\file", normalized)


    def test_jsonl_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "derive x"}}),
                        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": r"$x^2$"}]}}),
                    ]
                ),
                encoding="utf-8",
            )
            text = MODULE.parse_jsonl(path)
            self.assertIn("derive x", text)
            self.assertIn("$x^2$", text)

    def test_rendered_message_blocks(self):
        source = "# Title\n\nInline $x^2$\n\n\\[\n\\frac{a}{b}\n\\]\n\n| A | B |\n|---|---|\n| 1 | **two** |"
        rendered = MODULE.render_markdown_html(source)
        self.assertIn('class="formula formula-inline"', rendered)
        self.assertIn('class="formula formula-display"', rendered)
        self.assertIn("<table>", rendered)
        self.assertIn("class=\"line-pick\"", rendered)

    def test_code_block_keeps_literal_delimiters(self):
        source = "```text\n\\\\(literal)\\\\[value]\\\\frac{x}{y}\n```"
        rendered = MODULE.render_markdown_html(source)
        self.assertIn(r"\\(literal)\\[value]\\frac{x}{y}", rendered)
        self.assertNotIn('class="formula', rendered)

    def test_metadata_messages_are_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "internal_chat_message_metadata_passthrough": {"content_item_kinds": ["agents_md.instructions"]}, "content": [{"text": "# AGENTS.md instructions"}]}}),
                        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "<environment_context>hidden</environment_context>\nreal request"}]}}),
                        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": "answer"}]}}),
                    ]
                ),
                encoding="utf-8",
            )
            messages = MODULE.parse_jsonl_messages(path)
            self.assertEqual([message["text"] for message in messages], ["real request", "answer"])
