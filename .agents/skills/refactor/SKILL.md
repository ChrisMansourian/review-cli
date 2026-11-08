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

## Rule Index

Every rule ID the reviewer emits under `quality/*`, and where its playbook lives below.

| Rule ID | Severity | Playbook |
|---|---|---|
| `quality/mutable-default-argument` | ERROR | Mutable Default Arguments |
| `quality/unnecessary-else-after-return` | WARNING | Unnecessary else |
| `quality/complex-if-else-chain` | WARNING | Dispatch dict / match |
| `quality/duplicated-code-pattern` | WARNING | Extract helper |
| `quality/deep-nesting` | WARNING | Guard clauses |
| `quality/redundant-boolean-return` | WARNING | Boolean simplification |
| `quality/nested-ternary` | WARNING | Nested ternaries |
| `quality/long-parameter-list` | WARNING | Options object |
| `quality/bare-except` | WARNING | Exceptions |
| `quality/swallowed-exception` | WARNING | Exceptions |
| `quality/loose-equality` | WARNING | `===` |
| `quality/unreachable-code` | WARNING | Dead code |
| `quality/god-function` | WARNING | Decompose by responsibility |
| `quality/magic-literal-repetition` | INFO | Named constant |
| `quality/non-idiomatic-comparison` | INFO | `is None` / truthiness |
| `quality/range-len-loop` | INFO | `enumerate` / `zip` |
| `quality/manual-accumulation-loop` | INFO | Comprehension / pipeline |
| `quality/string-concatenation` | INFO | f-string / template literal |
| `quality/await-in-loop` | INFO | `Promise.all` / `gather` |
| `quality/collapsible-if` | INFO | Merge conditions |
| `quality/commented-out-code` | INFO | Delete it |
| `quality/narrating-comment` | INFO | Delete or explain why |

The detectors are line-based heuristics. If a finding is a false positive, don't contort
the code. Add `# reviewer:ignore` (or `// reviewer:ignore`) on that line and say so in the PR.

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

### `quality/duplicated-code-pattern` — Structural Variants

#### Repeated Attribute Access (Feature Envy)
```python
# Bad
print(user.profile.address.city)
validate(user.profile.address.city)
log(user.profile.address.city)

# Fix — bind to a local
city = user.profile.address.city
print(city); validate(city); log(city)
```

#### Repeated Object Construction
```python
# Bad — built 3× with minor differences
Response(status=200, headers=default_headers, body=body_a)
Response(status=200, headers=default_headers, body=body_b)
Response(status=200, headers=default_headers, body=body_c)

# Fix — factory / partial
def _ok_response(body) -> Response:
    return Response(status=200, headers=default_headers, body=body)
```

---

### `quality/deep-nesting` — Guard Clauses / Pyramid of Doom

**Pattern:** Deeply nested `if` blocks that push the happy path to the right.

```python
# Bad
def process(user):
    if user:
        if user.is_active:
            if user.has_permission("write"):
                do_work(user)

# Fix — invert conditions, return early
def process(user):
    if not user:
        return
    if not user.is_active:
        return
    if not user.has_permission("write"):
        return
    do_work(user)
```

**Rules:**
- Each guard handles one invalid state and exits immediately.
- Happy path stays at the leftmost indentation level.
- Works in any language — replace `return` with `throw`/`raise` where appropriate.

---

### `quality/redundant-boolean-return` — Boolean Simplification

```python
# Bad
if condition:
    return True
else:
    return False

# Fix
return condition

# Also bad
flag = True if x > 0 else False
# Fix
flag = x > 0
```

```typescript
// Bad
if (isValid) { return true; } else { return false; }
// Fix
return isValid;
```

---

### `quality/nested-ternary`

```python
# Bad — unreadable after 2 levels
label = "admin" if is_admin else ("mod" if is_mod else ("user" if is_user else "guest"))

# Fix — a small function with early returns
def role_label(user) -> str:
    if user.is_admin:
        return "admin"
    if user.is_mod:
        return "mod"
    if user.is_user:
        return "user"
    return "guest"

# If you already have a single `role` key, a lookup table is simpler:
label = ROLE_LABELS.get(role, "guest")
```

```typescript
// Bad
const label = isAdmin ? "admin" : isMod ? "mod" : isUser ? "user" : "guest";
// Fix — early-return helper
function roleLabel(u: User): string {
    if (u.isAdmin) { return "admin"; }
    if (u.isMod) { return "mod"; }
    if (u.isUser) { return "user"; }
    return "guest";
}
```

**Rule:** More than one level of ternary nesting → refactor.

---

### `quality/long-parameter-list` (5+ positional args)

```python
# Bad
def create_user(name, email, role, is_active, created_by, send_welcome):
    ...

# Fix — options dataclass/TypedDict
@dataclass
class CreateUserOptions:
    name: str
    email: str
    role: str
    is_active: bool = True
    created_by: str | None = None
    send_welcome: bool = True

def create_user(opts: CreateUserOptions) -> User:
    ...
```

```typescript
// Fix — options object with interface
interface CreateUserOptions {
    name: string;
    email: string;
    role: string;
    isActive?: boolean;
    createdBy?: string;
    sendWelcome?: boolean;
}
function createUser(opts: CreateUserOptions): User { ... }
```

**Rule:** 5+ positional parameters → use an options object, or make the extras keyword-only
(`def f(a, b, *, c, d, e)`). Keyword-only params and `self`/`cls` are not counted.

---

### `quality/manual-accumulation-loop` — Manual Loop → Collection Pipeline

```python
# Bad
result = []
for item in items:
    if item.is_active:
        result.append(item.name.upper())

# Fix
result = [item.name.upper() for item in items if item.is_active]
# If the transform is too complex for one line, extract it into a named function
# and call it from the comprehension rather than reaching for map/filter + lambda.
```

```typescript
// Bad
const result: string[] = [];
for (const item of items) {
    if (item.isActive) { result.push(item.name.toUpperCase()); }
}
// Fix
const result = items
    .filter(item => item.isActive)
    .map(item => item.name.toUpperCase());
```

---

### `quality/bare-except` / `quality/swallowed-exception`

```python
# Bad — catches KeyboardInterrupt/SystemExit and hides every bug
try:
    sync()
except:
    pass

# Fix — catch what you expect, and do something with it
try:
    sync()
except (ConnectionError, TimeoutError) as exc:
    logger.warning("sync skipped: %s", exc)
```

```typescript
// Bad
try { await sync(); } catch (e) {}
fetchData().catch(() => {});

// Fix
try {
    await sync();
} catch (err) {
    logger.warn("sync skipped", err);
}
```

**Rules:**
- Narrow the exception type first; only then decide whether to log, recover, or re-raise.
- If ignoring really is correct, keep the empty handler but add a comment saying *why*
  (a comment body is not flagged).
- Never catch-and-rethrow without adding context: either wrap (`raise X from exc`) or don't catch.

---

### `quality/non-idiomatic-comparison` (Python)

| Bad | Fix |
|---|---|
| `x == None` / `x != None` | `x is None` / `x is not None` |
| `flag == True` | `flag` (or `flag is True` if you need to exclude truthy non-bools) |
| `len(items) == 0` | `not items` |
| `len(items) > 0` | `items` |

Careful: `if not value` is also true for `0` and `""`. If those are valid values, use `is None`.

---

### `quality/loose-equality` (JS/TS)

```typescript
if (count == 0) { ... }    // Bad: "" == 0 is true
if (count === 0) { ... }   // Fix
```

`value == null` is allowed as the one idiomatic loose check (it matches `null` and `undefined`).

---

### `quality/range-len-loop` (Python)

```python
# Bad
for i in range(len(users)):
    send(users[i], tokens[i])

# Fix
for user, token in zip(users, tokens, strict=True):
    send(user, token)

# Need the index too?
for i, user in enumerate(users):
    ...
```

---

### `quality/await-in-loop`

```typescript
// Bad — N sequential round-trips
for (const id of ids) {
    users.push(await fetchUser(id));
}

// Fix — concurrent
const users = await Promise.all(ids.map(fetchUser));
```

```python
users = await asyncio.gather(*(fetch_user(i) for i in ids))
```

**Only apply when iterations are independent.** If each step depends on the previous one,
or you must rate-limit, sequential is correct. Leave it and add `# reviewer:ignore` with a reason.

---

### `quality/collapsible-if`

```python
# Bad
if user:
    if user.is_admin:
        grant(user)

# Fix
if user and user.is_admin:
    grant(user)
```

Only flagged when the inner `if` is the sole statement and neither has an `else`.

---

### `quality/commented-out-code`

Delete it. Git keeps the history. If it's a known-future change, replace it with a tracked
`TODO(#123)` that describes the intent in words, not code.

---

### `quality/narrating-comment`

```python
# Bad — restates the code
# Increment the counter
counter += 1

# Fix — delete it, or say *why*
# Count retries separately so the backoff resets after a success.
counter += 1
```

**Rules:**
- A comment earns its place by explaining intent, constraints, or non-obvious consequences.
- Don't write a comment to explain unclear code. Rename the variable or extract a function.

---

### Callback Hell → Async/Await *(not auto-detected)*

```typescript
// Bad
fetchUser(id, (user) => {
    fetchProfile(user.profileId, (profile) => {
        fetchPermissions(profile.id, (perms) => {
            render(user, profile, perms);
        });
    });
});

// Fix
async function loadUserView(id: string): Promise<void> {
    const user = await fetchUser(id);
    const profile = await fetchProfile(user.profileId);
    const perms = await fetchPermissions(profile.id);
    render(user, profile, perms);
}
```

---

### Primitive Obsession / Data Clumps *(not auto-detected)*

```python
# Bad — same 3 values always travel together
def send_email(to_address, to_name, to_domain): ...
def validate_email(to_address, to_name, to_domain): ...

# Fix — encapsulate into a type
@dataclass(frozen=True)
class EmailAddress:
    address: str
    name: str

    @property
    def domain(self) -> str:
        return self.address.split("@")[1]
```

---

### `quality/unreachable-code` — Dead Code After Return

```python
# Bad
def get_value():
    return 42
    print("done")     # never runs

# Bad
if True:
    do_a()
else:
    do_b()            # never runs
```

**Fix:** Delete the unreachable code entirely. If it was guarded by a feature flag, use a proper toggle instead of a hardcoded boolean.

---

### `quality/string-concatenation` — Template / f-string

```python
# Bad
msg = "Hello " + user.name + "! You have " + str(count) + " messages."

# Fix
msg = f"Hello {user.name}! You have {count} messages."
```

```typescript
// Bad
const msg = "Hello " + user.name + "! You have " + count + " messages.";
// Fix
const msg = `Hello ${user.name}! You have ${count} messages.`;
```

---

### `quality/god-function` — Function Doing Too Much

**Signal:** Function body > 50 non-blank lines (flagged), or its name contains "and" / "or" / multiple verbs.

```python
# Bad — one function: validates, persists, emails, logs
def register_user(data):
    # 80 lines of mixed concerns

# Fix — decompose by responsibility
def register_user(data: dict) -> User:
    validated = _validate_registration(data)
    user = _persist_user(validated)
    _send_welcome_email(user)
    _log_registration(user)
    return user
```

**Rules:**
- Each extracted function should be testable in isolation.
- Functions should have one reason to change (Single Responsibility).
- After decomposition, the top-level function reads like a table of contents.

---

### `quality/mutable-default-argument` (Python, ERROR)

```python
# Bad — shared mutable default, classic Python footgun
def append_item(item, lst=[]):
    lst.append(item)
    return lst

# Fix
def append_item(item, lst=None):
    if lst is None:
        lst = []
    lst.append(item)
    return lst
```

---

### Optional Chaining / Null Guard Repetition *(not auto-detected)*

```python
# Bad
if user and user.profile and user.profile.address:
    city = user.profile.address.city
else:
    city = None

# Fix — don't chain getattr() calls; that hides typos and is harder to read.
# Give the object a method that owns the traversal:
city = user.city if user else None   # where User.city handles missing profile/address
```

```typescript
// Bad
const city = user && user.profile && user.profile.address
    ? user.profile.address.city
    : undefined;
// Fix
const city = user?.profile?.address?.city;
```

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
