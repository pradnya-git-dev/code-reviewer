"""
A stand-in for the Claude API for testing without incurring live model usage costs.

This does NOT use a model. It finds a handful of seeded patterns with plain string checks
and answers in the same JSON shape the real API uses. That is enough to exercise every
code path in this repo: structured output, the retry, the tool loop, prompt caching fields,
the MCP request, and batch submission.

Usage:
  $ python tests/fake_claude.py            # Prints the two exports to copy
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypedDict, Any

REQUESTS = []         # Every request body the fake received, for tests to inspect
HEADERS = []          # The matching request headers
SEEN_PREFIXES = set() # Cached prefixes, to mimic cache write then cache read

"""
CANNED_ADDITION_ISSUES is a list of (trigger_text, severity, confidence, issue, suggestion) tuples,
with each tuple containing the trigger text to look for in added lines of code in the diff and details 
of the canned addition issues to emit for it.

trigger_text: Text to look for in an added line
severity: "CRITICAL", "MAJOR", "MINOR", "OTHER"
confidence: A [0, 1] score for how sure the finding is
issue: What's wrong
suggestion: Suggestion to resolve the issue
"""
CANNED_ADDITION_ISSUES = [
  (
    'query = f"SELECT',
    "CRITICAL",
    0.95,
    "User input is formatted into the SQL string.",
    "Use a parameterized query with ? placeholders."
  ),
  (
    "offset = page * page_size",
    "MAJOR",
    0.90,
    "Page 1 now skips the first page of rows.",
    "Use (page - 1) * page_size."
  ),
  (
    "items=[]",
    "MINOR",
    0.75,
    "A list default is shared between calls.",
    "Default to None and create the list inside the function."
  ),
  (
    "except Exception:",
    "MAJOR",
    0.85,
    "The insert error is swallowed and the caller gets None.",
    "Let the exception propagate or log and re-raise."
  ),
  (
    "return now > expires_at",
    "CRITICAL",
    0.95,
    "The expiry check is inverted.",
    "Return now < expires_at."
  ),
  (
    "{password}",
    "CRITICAL",
    0.97,
    "The plaintext password is written to the log.",
    "Remove the password from the log line."
  ),
  (
    'SECRET = "',
    "CRITICAL",
    0.96,
    "A signing secret is committed to the repo.",
    "Read it from the environment."
  ),
  (
    "with_tax =",
    "MINOR",
    0.4,
    "The temporary variable could be inlined.",
    "Inline it."
  )
]

"""
CANNED_REMOVAL_ISSUES is a list of (removed_text, anchor_text, severity, confidence, issue, suggestion) tuples,
with each tuple containing the trigger/removed text to look for in removed lines of code in the diff and details 
of the canned removal issues to emit for it.

removed_text: Text to look for in a deleted line
anchor_text: Text identifying the surviving line where the finding is attached
severity: "CRITICAL", "MAJOR", "MINOR", "OTHER"
confidence: A [0, 1] score for how sure the finding is
issue: What's wrong
suggestion: Suggestion to resolve the issue
"""
CANNED_REMOVAL_ISSUES = [
  (
    "if not items:",
    "total = 0.0",
    "MAJOR",
    0.9,
    "An empty list now divides by zero.",
    "Keep the empty-list guard."
  ),
  (
    "if order is None:",
    'return order["status"]',
    "MAJOR",
    0.88,
    "find_order can return None and the result is indexed.",
    "Raise OrderNotFound when it is None."
  )
]

VisibleLine = tuple[str, int, str, bool]
RemovedLine = tuple[str, str]

def walk_diff(diff_text: str) -> tuple[list[VisibleLine], list[RemovedLine]]:
  """Parses a unified diff into visible and removed lines.

  Iterates over the diff and tracks the current file and line number using
  the `+++` and `@@` headers. Context lines and added lines are recorded as
  visible lines with their new-file line numbers. Removed lines have no
  new-file line number, so they are recorded without one.

  Args:
    diff_text: The full text of a unified diff, such as the output of
      `git diff`.

  Returns:
    A tuple `(visible, removed)` where:

    - `visible` is a list of `(file, line_number, text, is_addition)`
      tuples for each added or context line. `file` is the path with any
      `b/` prefix stripped, `line_number` is the 1-based line number in the
      new version of the file, `text` is the line without its leading
      diff marker, and `is_addition` is True for added lines and False for
      context lines.
    - `removed` is a list of `(file, text)` tuples for each removed line.
  """

  visible, removed = [], []
  current_file, line_number = None, 0

  for line in diff_text.splitlines():
    if line.startswith("+++ "):
      current_file = line[4:].strip().removeprefix("b/")
    elif line.startswith("@@"):
      line_number = int(line.split("+")[1].split(",")[0].split(" ")[0])
    elif current_file is None or line.startswith("---") or line.startswith("diff "):
      continue
    elif line.startswith("-"):
      removed.append((current_file, line[1:]))
    elif line.startswith("+") or line.startswith(" "):
      visible.append((current_file, line_number, line[1:], line.startswith("+")))
      line_number += 1
  return visible, removed

class Finding(TypedDict):
  file: str
  line_number: int
  severity: str
  confidence: float
  issue: str
  suggestion: str

def fake_findings(diff_text: str, pricing_was_read: bool) -> list[Finding]:
  """Builds canned review findings for a diff by matching seeded patterns.

  Args:
    diff_text: The full text of a unified diff.
    pricing_was_read: Whether the model has read pricing.py through a tool. The
      cross-file `apply_discount` finding is only emitted when this is True.

  Returns:
    A list of finding dicts with the keys `file`, `line_number`, `severity`,
    `confidence`, `issue`, and `suggestion`.
  """
  visible, removed = walk_diff(diff_text)
  findings = []

  def add(file: str, line_number: int, severity: str, confidence: float, issue: str, suggestion: str) -> None:
    findings.append({
      "file": file,
      "line_number": line_number,
      "severity": severity,
      "confidence": confidence,
      "issue": issue,
      "suggestion": suggestion
    })

  for file, line_number, text, is_addition in visible:
    for trigger_text, severity, confidence, issue, suggestion in CANNED_ADDITION_ISSUES:
      if is_addition and trigger_text in text:
        add(file, line_number, severity, confidence, issue, suggestion)
    # The cross-file bug is only visible after reading pricing.py through a tool.
    if is_addition and "apply_discount(subtotal, 15)" in text and pricing_was_read:
      add(file, line_number, "MAJOR", 0.9, "apply_discount expects a fraction, and 15 raises ValueError.", "Pass 0.15.")
  for removed_text, anchor_text, severity, confidence, issue, suggestion in CANNED_REMOVAL_ISSUES:
    for removed_file, removed_text in removed:
      if removed_text in removed_text:
        for file, line_number, text, _ in visible:
          if file == removed_file and anchor_text in text:
            add(file, line_number, severity, confidence, issue, suggestion)

  return findings

def message_text(message: dict[str, Any]) -> str:
  """Extracts the plain text from a Claude API message.

  Args:
    message: A message dict with a `content` key. The content is either a
      string or a list of content blocks (dicts), as in the Messages API.

  Returns:
    The content itself if it is a string. Otherwise, the text of each block
    joined by newlines, using the block's `text` value, or its `content`
    value if `text` is missing or empty. Blocks with neither contribute an
    empty string.
  """
  content = message["content"]
  if isinstance(content, str):
    return content
  return "\n".join(str(block.get("text") or block.get("content") or "") for block in content)

def answer(body):
  messages = body["messages"]
  diff_text = message_text(messages[0])
  everything = "\n".join(message_text(m) for m in messages)
  tool_names = [t.get("name") for t in body.get("tools", [])]
  content, stop_reason = [], "end_turn"

  wants_pricing = "get_file" in tool_names and "apply_discount(" in diff_text
  if wants_pricing and "tool_result" not in json.dumps(messages):
    content = [
      {
        "type": "tool_use",
        "id": "tool_use_fake_1",
        "name": "get_file",
        "input": {
          "path": "app/pricing.py"
        }
      }
    ]
    stop_reason = "tool_use"
  elif "output_config" in body:
    findings = fake_findings(diff_text, "fraction between 0 and 1" in everything)
    if os.environ.get("FAKE_CLAUDE_BAD_LINE") and "The following issues were identified with your previous response." not in everything:
      findings.insert(0, {
        "severity": "MAJOR",
        "file": findings[0]["file"] if findings else "app/x.py",
        "line_number": 9999,
        "issue": "Invented line.",
        "suggestion": "None.",
        "confidence": 0.9
      })
    payload = { "findings": findings }
    if "suggested_tests" in json.dumps(body["output_config"]):
      payload["suggested_tests"] = []
    content = [{
      "type": "text",
      "text": json.dumps(payload)
    }]
  else:
    lines = [f"{f['file']} line {f['line_number']}: {f['issue']} {f['suggestion']}" for f in fake_findings(diff_text, False)]
    text = "\n".join(lines) or "No issues found."
    if body.get("max_tokens", 1024) < 100:
      text, stop_reason = text[:80], "max_token"
    content = [{ "type": "text", "text": text }]

  usage = {
    "input_tokens": len(json.dumps(messages)) // 4,
    "output_tokens": len(json.dumps(content)) // 4,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  }

  system = body.get("system")
  if isinstance(system, list) and any("cache_control" in block for block in system):
    prefix = json.dumps([body.get("tools"), system], sort_keys=True)
    size = len(prefix) // 4
    if prefix in SEEN_PREFIXES:
      usage["cache_read_input_tokens"] = size
    else:
      SEEN_PREFIXES.add(prefix)
      usage["cache_creation_input_tokens"] = size

  return { 
    "id": "msg_fake",
    "type": "message",
    "role": "assistant",
    "model": body.get("model", "fake"),
    "content": content,
    "stop_reason": stop_reason,
    "stop_sequence": None,
    "usage": usage
  }

class Handler(BaseHTTPRequestHandler):
  def do_POST(self):
    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    REQUESTS.append(body)
    HEADERS.append({ k.lower(): v for k, v in self.headers.items() })
    if "/batches" in self.path:
      reply = {
        "id": "msgbatch_fake",
        "type": "message_batch",
        "processing_status": "in_progress",
        "request_counts": {
          "processing": len(body["requests"]),
          "succeeded": 0,
          "errored": 0,
          "canceled": 0,
          "expired": 0
        },
        "created_at": "2026-10-01T00:00:00Z", 
        "expires_at": "2026-10-02T00:00:00Z",
        "ended_at": None,
        "cancel_initiated_at": None,
        "archived_at": None,
        "results_url": None
      }
    else:
      reply = answer(body)

    data = json.dumps(reply).encode()
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def log_message(self, *args, **kwargs):      # Keeps test output quiet
    pass

def start(port=0):
  server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  return server, f"http://127.0.0.1:{server.server_address[1]}"

if __name__ == "__main__":
    server, url = start(8765)
    print("Fake Claude is listening. In another terminal, run:\n")
    print(f"  export ANTHROPIC_BASE_URL={url}\n  export ANTHROPIC_API_KEY=fake-key\n")
    threading.Event().wait()