# Canned provider responses

Each fixture diff has a sibling directory under this folder containing canned
LLM-provider responses keyed by provider name:

```text
tests/fixtures/responses/<fixture-name>/<provider>.json
```

Example:

```text
tests/fixtures/responses/02-pascalcase-bug/deepseek.json
tests/fixtures/responses/02-pascalcase-bug/anthropic.json
```

The `tests/support/fixture_server.py` HTTP fixture server reads these on each
request. Tests select which fixture's responses to serve via the
`X-Test-Fixture` header on the test-runner subprocess invocation.

JSON shape mirrors the real provider response:

- DeepSeek: `{"choices":[{"message":{"content":"...","reasoning_content":"..."}}],"usage":{...}}`
- Anthropic: `{"content":[{"type":"text","text":"..."}],"usage":{...}}`

The `content`/`text` field should be the reviewer's JSON-formatted findings list
per `contracts/finding-schema.md#llm-reviewer-output`. Empty findings are
represented by an empty array literal in the field text: `"[]"`.
