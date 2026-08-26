"""fixture_server.request_prompts understands every provider's REQUEST shape.

The response side of the fixture server has been provider-agnostic since the
`any.json` tier landed. The request side was not, and the asymmetry cost three
tests: test_context_delivery parsed recorded bodies as `json.loads(raw)["messages"]`,
which is the DeepSeek/OpenAI chat shape. Google sends `contents` and
`system_instruction`, so when the broad-pass default moved to google every body
parsed to no prompts, and three assertions about whether context reaches the
provider stopped being about anything. They surfaced as "context delivery is
broken" — it was not, and it never had been.

So the extractor is tested against each provider's real payload rather than
against a hand-written approximation of it: every case below builds its body by
monkeypatching the provider module's HTTP call and invoking `call()`, so a
provider that changes its wire shape fails HERE, naming itself, instead of
quietly emptying a prompt list in an integration test.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review_plan_v2.providers import (
    anthropic,
    deepseek,
    google,
    openai,
    registry,
)
from support.fixture_server import request_prompts

SYSTEM = "You are the **security** code reviewer."
USER = "[File: web/src/lib/server/caller.ts | lines 1-10]\nerrCode: string | null"

# Each provider module posts through its own `_post_once(url, headers, payload, timeout)`.
# Capturing `payload` there gets the exact dict that would go on the wire.
_MODULES = {
    "deepseek": deepseek,
    "openai": openai,
    "google": google,
    "anthropic": anthropic,
}

# Minimal successful response per provider, so `call()` returns rather than retrying
# for the length of its backoff schedule.
_OK = {
    "deepseek": {"choices": [{"message": {"content": "[]"}}]},
    "openai": {"choices": [{"message": {"content": "[]"}}]},
    "anthropic": {"content": [{"type": "text", "text": "[]"}]},
    "google": {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]},
}


def _captured_payload(tag: str) -> str:
    """The JSON body `tag`'s provider module would actually POST, as a string."""
    mod = _MODULES[tag]
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen["payload"] = payload
        return 200, json.dumps(_OK[tag]).encode("utf-8")

    env = {var: "test-key" for var in registry.KEY_ENV[tag]}
    # autospec, with fake_post as a side_effect rather than as `new`. Passing a
    # replacement directly disables signature checking entirely: `_post_once`
    # could grow a required parameter, `call()` could be updated to pass it, and
    # fake_post would keep accepting the old four positionally and this test would
    # keep passing against an interface that no longer exists. autospec binds the
    # call against the REAL signature, so that drift fails here instead.
    with mock.patch.dict("os.environ", env, clear=False), \
            mock.patch.object(mod, "_post_once", autospec=True) as post:
        post.side_effect = fake_post
        mod.call(SYSTEM, USER, model="test-model", reviewer="security")
    if "payload" not in seen:
        raise AssertionError(
            f"{tag}.call() never reached _post_once, so this test captured no payload "
            f"and would pass vacuously. Its request path changed shape."
        )
    return json.dumps(seen["payload"])


class EveryProviderShapeIsUnderstood(unittest.TestCase):
    def test_all_tags_round_trip_through_the_extractor(self):
        # ALL_TAGS, not REVIEW_CAPABLE. Two tags are refused as reviewers but their
        # modules stay importable, and a tag returning to capability must not need a
        # matching change here to be visible.
        for tag in registry.ALL_TAGS:
            with self.subTest(provider=tag):
                parsed = request_prompts(_captured_payload(tag))
                self.assertIsNotNone(
                    parsed,
                    msg=f"{tag}'s request body parsed to no prompts at all. A test "
                        f"reading bodies would silently see nothing from {tag}.",
                )
                system, user = parsed
                self.assertIn(SYSTEM, system, msg=tag)
                self.assertIn(USER, user, msg=tag)

    def test_the_system_and_user_prompts_are_not_conflated(self):
        """_prompts_for filters by reviewer on the SYSTEM half and matches the file
        on the USER half. Returning both concatenated in both slots would satisfy
        every assertion in test_context_delivery while proving nothing about which
        reviewer was asked."""
        for tag in registry.ALL_TAGS:
            with self.subTest(provider=tag):
                system, user = request_prompts(_captured_payload(tag))
                self.assertNotIn(USER, system, msg=f"{tag}: user prompt leaked into system")
                self.assertNotIn(SYSTEM, user, msg=f"{tag}: system prompt leaked into user")


class NonPromptTrafficIsSkippedNotMisread(unittest.TestCase):
    """Returning None rather than ("", "") matters: a caller that unpacks the result
    would get two empty strings from a body it should have skipped, and an empty
    system string passes no reviewer filter but an empty user string passes no file
    filter either — so the failure would be invisible instead of a TypeError."""

    def test_non_json_is_none(self):
        self.assertIsNone(request_prompts("not json at all"))

    def test_json_that_is_not_an_object_is_none(self):
        self.assertIsNone(request_prompts("[1, 2, 3]"))
        self.assertIsNone(request_prompts('"a string"'))

    def test_an_unrecognised_object_is_none(self):
        self.assertIsNone(request_prompts('{"model": "x", "prompt": "legacy"}'))

    def test_messages_of_the_wrong_type_is_none(self):
        self.assertIsNone(request_prompts('{"messages": "not a list"}'))

    def test_empty_prompts_are_none_rather_than_a_pair_of_blanks(self):
        self.assertIsNone(request_prompts('{"messages": []}'))
        self.assertIsNone(request_prompts('{"contents": []}'))


class ContentBlockListsAreUnderstood(unittest.TestCase):
    """`content` as a list of typed blocks, which both Anthropic and OpenAI accept.

    No provider here sends that shape today — EveryProviderShapeIsUnderstood proves
    it by capturing their real payloads — so these are about the failure MODE if one
    switches, not about current behaviour. The string-only extractor returned "" for
    every block-list message, which is not a visible error anywhere: the prompt lists
    in test_context_delivery come back empty and its three assertions fail on their
    own `assertTrue(prompts)` guard, reading "context delivery is broken" when
    delivery is fine and the parser is blind. A parser keyed to one spelling of a
    field inside the right format is the same defect as a fixture named after one
    provider; this file exists because that one already cost a session.
    """

    def test_openai_shape_with_block_lists(self):
        body = json.dumps({"messages": [
            {"role": "system", "content": [{"type": "text", "text": SYSTEM}]},
            {"role": "user", "content": [{"type": "text", "text": USER}]},
        ]})
        self.assertEqual(request_prompts(body), (SYSTEM, USER))

    def test_anthropic_shape_with_a_block_list_system(self):
        body = json.dumps({
            "system": [{"type": "text", "text": SYSTEM}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": USER}]}],
        })
        self.assertEqual(request_prompts(body), (SYSTEM, USER))

    def test_mixed_string_and_block_list_messages(self):
        body = json.dumps({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": USER}]},
        ]})
        self.assertEqual(request_prompts(body), (SYSTEM, USER))

    def test_multiple_blocks_in_one_message_are_joined(self):
        body = json.dumps({"messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]},
        ]})
        self.assertEqual(request_prompts(body), ("", "first\nsecond"))

    def test_non_text_blocks_are_dropped_not_crashed_on(self):
        # An image block has no "text" key. Skipping it must not raise, and must not
        # discard the text blocks beside it.
        body = json.dumps({"messages": [
            {"role": "user", "content": [
                {"type": "image", "source": {"data": "..."}},
                {"type": "text", "text": USER},
            ]},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_a_block_list_with_no_text_at_all_is_none_not_a_blank_pair(self):
        body = json.dumps({"messages": [
            {"role": "user", "content": [{"type": "image", "source": {}}]},
        ]})
        self.assertIsNone(request_prompts(body))

    def test_a_null_content_does_not_raise(self):
        """`{"role": "assistant", "content": null}` is the standard OpenAI shape for
        a message that carries tool calls instead of text, so it is real traffic
        rather than a hypothetical — round memory is the obvious way a multi-turn
        body reaches this parser.

        `_text` returns "" for it, which is already correct. The test is here
        because that correctness is a `return ""` fallthrough nothing exercised,
        and the failure mode if it went away is not an exception in a test: it is
        a TypeError raised inside the fixture server's request handler, which
        surfaces as the reviewer call failing and reads as a provider fault. The
        google branch had exactly this hole for `"text": None` until
        `test_a_null_text_part_does_not_raise` was added; this is the same hole on
        the chat side.
        """
        body = json.dumps({"messages": [
            {"role": "user", "content": USER},
            {"role": "assistant", "content": None},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_a_message_whose_only_content_is_null_is_none_not_a_blank_pair(self):
        # Anti-vacuity twin of the case above: "did not raise" must not be
        # satisfied by silently inventing an empty prompt pair, which a caller
        # would read as "the request carried no prompt" — the same silent miss
        # request_prompts exists to remove.
        body = json.dumps({"messages": [{"role": "user", "content": None}]})
        self.assertIsNone(request_prompts(body))


class GooglePartListsAreUnderstoodTheSameWay(unittest.TestCase):
    """The `contents`/`parts` half of the same property, which had NO coverage.

    Every case above exercises the chat/Anthropic branch and `_text`. Google
    bodies go through a separate `_parts` helper, and the class above being named
    for the general property while testing only one of the two branches is how
    the asymmetry stayed invisible: `_text` guarded `isinstance(b.get("text"),
    str)` and `_parts` used a bare `p.get("text", "")`, which defaults only a
    MISSING key. A `"text": null` part, or a non-text part whose `text` is not a
    string, made `"\\n".join` raise TypeError inside the fixture server's request
    handler — a harness crash presenting as a provider failure.
    """

    def test_google_shape_single_part(self):
        body = json.dumps({
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": USER}]}],
        })
        self.assertEqual(request_prompts(body), (SYSTEM, USER))

    def test_google_camel_case_system_instruction(self):
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": USER}]}],
        })
        self.assertEqual(request_prompts(body), (SYSTEM, USER))

    def test_multiple_google_parts_are_joined(self):
        body = json.dumps({"contents": [
            {"role": "user", "parts": [{"text": "first"}, {"text": "second"}]},
        ]})
        self.assertEqual(request_prompts(body), ("", "first\nsecond"))

    def test_non_text_google_parts_are_dropped_not_crashed_on(self):
        body = json.dumps({"contents": [
            {"role": "user", "parts": [
                {"inline_data": {"mime_type": "image/png", "data": "..."}},
                {"text": USER},
            ]},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_a_null_text_part_does_not_raise(self):
        """The case a `.get("text", "")` default does NOT cover.

        A missing key defaults to ""; a present-but-null one yields None, and
        joining None is a TypeError, not an empty string.
        """
        body = json.dumps({"contents": [
            {"role": "user", "parts": [{"text": None}, {"text": USER}]},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_a_non_string_text_part_does_not_raise(self):
        body = json.dumps({"contents": [
            {"role": "user", "parts": [{"text": {"nested": "dict"}}, {"text": USER}]},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_google_parts_with_no_text_at_all_is_none_not_a_blank_pair(self):
        body = json.dumps({"contents": [
            {"role": "user", "parts": [{"inline_data": {"data": ""}}]},
        ]})
        self.assertIsNone(request_prompts(body))

    def test_a_parts_entry_that_is_not_a_dict_is_skipped(self):
        body = json.dumps({"contents": [
            {"role": "user", "parts": ["a bare string", {"text": USER}]},
        ]})
        self.assertEqual(request_prompts(body), ("", USER))


class MultiTurnBodiesReadTheSameOnBothShapes(unittest.TestCase):
    """A conversation with prior turns must yield the same halves either way.

    The google branch joined every `contents` entry regardless of role while the
    chat branch took `role == "user"` only, so the two disagreed on the same
    conversation. Nothing sends a multi-turn body today — google.py posts one
    `role: "user"` entry — so this is about the failure MODE, like the block-list
    cases above: the model's own prior output landing in the "user" half is not a
    crash, it is an assertion that can be satisfied by the model having mentioned
    the thing the test was looking for. Two providers, one extractor, one answer.
    """

    PRIOR = "prior answer mentioning caller.ts"

    def test_chat_shape_drops_assistant_turns(self):
        body = json.dumps({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
            {"role": "assistant", "content": self.PRIOR},
        ]})
        system, user = request_prompts(body)
        self.assertEqual(system, SYSTEM)
        self.assertEqual(user, USER)
        self.assertNotIn(self.PRIOR, user)

    def test_google_shape_drops_model_turns(self):
        body = json.dumps({
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [
                {"role": "user", "parts": [{"text": USER}]},
                {"role": "model", "parts": [{"text": self.PRIOR}]},
            ],
        })
        system, user = request_prompts(body)
        self.assertEqual(system, SYSTEM)
        self.assertEqual(user, USER)
        self.assertNotIn(self.PRIOR, user)

    def test_both_shapes_agree_on_the_same_conversation(self):
        chat = json.dumps({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "first ask"},
            {"role": "assistant", "content": self.PRIOR},
            {"role": "user", "content": "second ask"},
        ]})
        goog = json.dumps({
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [
                {"role": "user", "parts": [{"text": "first ask"}]},
                {"role": "model", "parts": [{"text": self.PRIOR}]},
                {"role": "user", "parts": [{"text": "second ask"}]},
            ],
        })
        self.assertEqual(request_prompts(chat), request_prompts(goog))
        self.assertEqual(request_prompts(goog), (SYSTEM, "first ask\nsecond ask"))

    def test_a_contents_entry_with_no_role_still_counts_as_user(self):
        # Dropping a role-less entry would empty the user half of a single-turn
        # body that omits it, which the REST API permits.
        body = json.dumps({"contents": [{"parts": [{"text": USER}]}]})
        self.assertEqual(request_prompts(body), ("", USER))

    def test_a_body_of_only_model_turns_is_none_not_a_blank_pair(self):
        body = json.dumps({"contents": [
            {"role": "model", "parts": [{"text": self.PRIOR}]},
        ]})
        self.assertIsNone(request_prompts(body))


class GoogleSpellingVariants(unittest.TestCase):
    """google.py sends `system_instruction`; the REST API also accepts
    `systemInstruction`. Accepting both means a switch between them is not a
    silent loss of the reviewer filter."""

    def _body(self, key: str) -> str:
        return json.dumps({
            key: {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": USER}]}],
        })

    def test_snake_case(self):
        self.assertEqual(request_prompts(self._body("system_instruction")), (SYSTEM, USER))

    def test_camel_case(self):
        self.assertEqual(request_prompts(self._body("systemInstruction")), (SYSTEM, USER))

    def test_the_spelling_google_actually_sends_is_one_of_them(self):
        # Anti-staleness: if google.py moves to a third spelling, the two tests above
        # keep passing against bodies nothing sends.
        body = json.loads(_captured_payload("google"))
        self.assertTrue(
            "system_instruction" in body or "systemInstruction" in body,
            msg=f"google.py sends neither spelling this test accepts: {sorted(body)}",
        )


if __name__ == "__main__":
    unittest.main()
