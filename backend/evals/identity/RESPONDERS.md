# Answering an identity eval request (responder brief)

You stand in for the app's model on one request of the identity evaluation, when no API
key is available. Your answer is parsed by the app's own code. Answer exactly as the
model named in the request would.

## What you get

One or more request files, `<token>.<n>.json` (resolver v2: an opaque token, call `n`)
or `<name>.json` (legacy resolver). Each holds what the app sends on the wire:

- `purpose`: `identity` (the small model, every turn) or `identity_strong` (the second
  opinion on the mentions the first call left risky); `model`: the model you emulate.
  The dispatcher gives `identity` requests to a Haiku-class responder and
  `identity_strong` requests to a Sonnet-class one;
- `system`: the system prompt;
- `messages`: the user message (the narration, the candidate cards, what is already
  resolved, the scene, and for `identity_strong` the mentions to decide);
- `tools` (resolver v2 on Anthropic): the one tool to answer with, and its
  `input_schema`, or `response_format` with a `schema`;
- `max_tokens`, `thinking` and other wire options: context only.

## What you write

For each request, one file next to it, same name with `.txt` instead of `.json`
(`<token>.<n>.txt`), holding only the raw output text:

- with `tools` or `response_format`: the JSON object of the tool input, matching the
  schema (for the resolver v2, `{"mentions": [...]}`), nothing else;
- without them: exactly the text the system prompt asks for (for the legacy resolver,
  its JSON object).

No preamble, no explanation, no markdown around it (a code fence is tolerated, not
wanted). Follow the system prompt and the schema to the letter: only the handles,
decisions, kinds and types they allow, every surface copied from the narration as it is
written. Decide each mention from the request alone, the way the model would; do not
aim at a score.

## Rules

- You may read only the request files you were given, and write only their matching
  `.txt` files. Open, list or search no other file or directory, and run no command:
  an answer informed by anything else than the request is worthless.
- Never edit a request file.
- One request, one answer. A later call (`<token>.<n+1>.json`) comes as a new request
  once your answer has been replayed.
- If the request seems malformed, still answer as the model would; report the doubt to
  the dispatcher, never in the answer file.

## For the dispatcher

`DIR/pending.json` lists the requests to answer (`file`, `purpose`, `model`); route each
by `purpose`, and give each responder the section above, the paths of its request files
and nothing else (no repository path, no scene id, no file of the evaluation).
Run the same command again once every listed request has its `.txt`: the
replay writes the next stage, until `pending.json` is empty and the report is written.
The report header carries the responder (`--responder subagent:claude-haiku+claude-sonnet`)
and says these are subagent responders, to confirm with 3 API runs when a key exists.
