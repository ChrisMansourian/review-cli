---
name: refactor
description: >
  Guides the AI through fixing code quality violations flagged by the reviewer
  CLI. Provides a concrete, repeatable playbook for each quality/* rule so
  fixes are consistent and verifiable.
---

# Refactor Skill

Use this skill when asked to fix violations in `.reviewer/report.md`, or when
a user says something like *"fix the flagged issues"* / *"clean up the slop"*.

## Step 0 — Always Read the Report First

```
read_file(".reviewer/report.md")
```

If it doesn't exist, run the reviewer first:

```
reviewer --base main
```

Then work through each violation **by severity** (ERROR → WARNING → INFO).

---

## Playbooks by Rule ID

### `quality/unnecessary-else-after-return`

**Pattern being flagged:**
```python
if condition:
    return value
else:          # ← redundant
    do_thing()
```

**Fix — remove the else, dedent the block:**
```python
if condition:
    return value
do_thing()     # ← falls through naturally
```

**Rules:**
- Never change the logic — only restructure the control flow.
- If the else contains multiple statements, dedent all of them.
- Works identically in TypeScript/JS: remove `} else {`, dedent, close the outer block.
- Verify by re-reading the surrounding function to confirm early-return semantics are preserved.

---

### `quality/complex-if-else-chain`

**Pattern being flagged (3+ elif/else-if branches):**
```python
if action == "create":
    create()
elif action == "update":
    update()
elif action == "delete":
    delete()
elif action == "list":
    list_items()
```

**Fix — dispatch dict (Python):**
```python
_HANDLERS = {
    "create": create,
    "update": update,
    "delete": delete,
    "list":   list_items,
}

handler = _HANDLERS.get(action)
if handler is None:
    raise ValueError(f"Unknown action: {action!r}")
handler()
```

**Fix — match statement (Python 3.10+):**
```python
match action:
    case "create": create()
    case "update": update()
    case "delete": delete()
    case "list":   list_items()
    case _:        raise ValueError(f"Unknown action: {action!r}")
```

**Fix — object map (TypeScript/JS):**
```typescript
const handlers: Record<string, () => void> = {
    create: create,
    update: update,
    delete: deleteItem,
    list:   listItems,
};
const handler = handlers[action];
if (!handler) { throw new Error(`Unknown action: ${action}`); }
handler();
```

**Rules:**
- Always handle the default/unknown case explicitly (don't silently swallow it).
- If branches have *different signatures* (different args), use a strategy pattern or pass a context object.
- Module-level dispatch dicts are preferred over inline ones for reusability.
- After refactoring, run the existing tests to confirm behavior is unchanged.

---

### `quality/magic-literal-repetition`

**Pattern being flagged (same literal 3+ times):**
```python
time.sleep(30)
timeout = 30
max_wait = 30
```

**Fix — named constant at module or class scope:**
```python
_TIMEOUT_SECONDS = 30   # module-level

time.sleep(_TIMEOUT_SECONDS)
timeout = _TIMEOUT_SECONDS
max_wait = _TIMEOUT_SECONDS
```

**Naming conventions:**
| Context | Style |
|---|---|
| Python module-level | `SCREAMING_SNAKE_CASE` |
| Python class attribute | `SCREAMING_SNAKE_CASE` |
| TypeScript `const` | `SCREAMING_SNAKE_CASE` or `camelCase` |
| Go | `PascalCase` for exported, `camelCase` for unexported |

**Rules:**
- Pick the name from the *purpose* of the value, not its content (`MAX_RETRIES`, not `THREE`).
- Place the constant as close to its first use as is reasonable (module top, or class body).
- Replace **all** occurrences, not just the ones in the diff.
- Don't extract literals that are truly incidental (HTTP status `200` in a test assertion is fine).

---

### `quality/duplicated-code-pattern`

**Pattern being flagged (3+ near-identical adjacent lines):**
```python
db.execute(INSERT_USER_SQL, user_params)
db.execute(INSERT_USER_SQL, user_params)
db.execute(INSERT_USER_SQL, user_params)
```
or more realistically:
```python
logger.info("Creating user %s", user_id)
audit.log("Creating user %s", user_id)
metrics.increment("user.create")

logger.info("Deleting user %s", user_id)
audit.log("Deleting user %s", user_id)
metrics.increment("user.delete")
```

**Fix — extract helper, parameterise the varying parts:**
```python
def _log_user_action(action: str, user_id: str) -> None:
    logger.info("%s user %s", action, user_id)
    audit.log("%s user %s", action, user_id)
    metrics.increment(f"user.{action.lower()}")

_log_user_action("Creating", user_id)
_log_user_action("Deleting", user_id)
```

**Rules:**
- Identify what *varies* between copies — those become parameters.
- Identify what is *constant* — that becomes the function body.
- Name the helper after what it *does*, not what it *contains*.
- Keep helpers small and single-purpose. If the extracted function needs 5+ params, the original design may need a bigger rethink.
- After extraction, delete every copy and replace with the call.

---

## Step Last — Verify the Fix

After applying any refactor:

1. **Re-run reviewer** to confirm the violation is gone:
   ```
   reviewer --base main
   ```

2. **Run the test suite** to confirm no regressions:
   ```
   python -m unittest discover tests
   ```

3. **Commit with a conventional message:**
   ```
   refactor: extract duplicate X logic into helper / replace elif chain with dispatch dict
   ```

> [!IMPORTANT]
> Never change observable behavior during a refactor. If tests don't exist for the
> changed code, note it to the user and suggest adding them before merging.
