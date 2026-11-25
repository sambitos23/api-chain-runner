# API Chain Runner

A powerful Python CLI tool for executing chained API calls defined in YAML. Each step can reference responses from previous steps, generate unique test data, upload files, poll for expected values, retry on failures, and add delays between steps — all logged to CSV or Excel with IST timestamps.

Perfect for API testing, integration testing, workflow automation, and complex multi-step API scenarios.

## Quick Start

```bash
# 1. Clone the repo and set up a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run a chain
python -m api_chain_runner example_chain.yaml
```

## CLI Usage

```bash
# Default output: <config_name>_results.csv
python -m api_chain_runner my_chain.yaml

# Custom output path
python -m api_chain_runner my_chain.yaml -o output/results.csv

# Excel output
python -m api_chain_runner my_chain.yaml -o results.xlsx -f xlsx

# Launch web UI
python -m api_chain_runner --ui flow/

# Custom env file
python -m api_chain_runner my_chain.yaml -e production.env

# Check version
python -m api_chain_runner --version
```

## YAML Chain Format

A chain config has an optional `variables` block and a required `chain` list of steps:

```yaml
variables:
  my_token: "some-static-token"
  base_url: "https://api.example.com"

chain:
  - name: auth
    url: "${vars.base_url}/login"
    method: POST
    headers:
      Content-Type: "application/json"
    payload:
      email: "${ENV:AUTH_EMAIL}"
      password: "${ENV:AUTH_PASSWORD}"

  - name: get_user
    url: "${vars.base_url}/user"
    method: GET
    delay: 5
    headers:
      Authorization: "Bearer ${auth.token}"
    retry:
      max_attempts: 3
      delay: 2
      retry_on: ["timeout", "connection", "5xx"]
```

## Complete Step Fields Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | string | Unique step identifier, used for referencing responses |
| `url` | No* | string | Request URL (supports `${step.key}` references) — *required unless `manual: true` |
| `method` | No* | string | HTTP method (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`) — *required unless `manual: true` |
| `headers` | No | dict | Request headers as key-value pairs |
| `payload` | No | dict | JSON request body |
| `files` | No | dict | File uploads as `field_name: file_path` pairs (multipart/form-data) |
| `unique_fields` | No | dict | Auto-generate unique values — `dotted.path: type` where type is `email`, `pan`, `mobile`, or `udyam` |
| `extract` | No | dict | Extract values from response (legacy, use `eval_keys` instead) |
| `polling` | No | object | Retry until a response field matches an expected value |
| `delay` | No | int | Seconds to wait before executing this step (default: `0`) |
| `print_keys` | No | list | Response key paths to print to console after execution |
| `manual` | No | bool | If `true`, this is a manual step — no HTTP call, just shows instructions |
| `instruction` | No* | string | Text shown to the user during a manual step (*required if `manual: true`) |
| `print_ref` | No | list | List of `step.key` references to print from previous steps (for manual steps) |
| `condition` | No | object/list | Only execute this step if previous step(s) match condition(s) |
| `continue_on_error` | No | bool | If `false`, chain stops on failure (default: `true`) |
| `retry` | No | object/bool | Retry configuration for transient failures (default: 3 attempts on timeout/connection/5xx) |
| `eval_keys` | No | dict | Extract response values into named variables for evaluation |
| `eval_condition` | No | string | Python expression to evaluate using `eval_keys` variables |
| `success_message` | No | string | Message printed when `eval_condition` is true |
| `failure_message` | No | string | Message printed when `eval_condition` is false |

### Retry Configuration

Automatically retry steps that fail due to transient errors (timeouts, connection issues, 5xx errors):

```yaml
- name: fetch-data
  url: "https://api.example.com/data"
  method: GET
  retry:
    max_attempts: 3      # total attempts (default: 3)
    delay: 2             # seconds between retries (default: 5)
    retry_on:            # error types to retry on (default: ["timeout", "connection", "5xx"])
      - timeout
      - connection
      - 5xx
```

Retry types:
- `timeout` — request timed out
- `connection` — connection refused / DNS failure
- `5xx` — server returned 500-599
- `4xx` — server returned 400-499 (use with caution)

To disable retries for a step:

```yaml
retry: false
```

Default behavior (if `retry` is omitted): 3 attempts on timeout/connection/5xx errors.

Console output during retry:

```
[5/21] ▶ application-creation running....
         🔄 [retry] Attempt 1/3 failed — HTTP 504
         🔄 [retry] Waiting 5s before next attempt...
         🔄 [retry] Attempt 2/3 failed — HTTP 504
         🔄 [retry] Waiting 5s before next attempt...
         🔄 [retry] Succeeded on attempt 3/3
         ✅ Passed — HTTP 200 (1205ms)
```

Each retry attempt is logged to the console so you can watch the progression. Only the final result (success or exhausted retries) is logged to CSV.

### Delay Between Steps

Add a delay (in seconds) before a step executes. Useful when the previous API needs time to process before the next call:

```yaml
- name: check-status
  url: "https://api.example.com/status?id=${create_lead.leadId}"
  method: GET
  delay: 20    # wait 20 seconds after the previous step completes
  headers:
    Authorization: "Bearer ${auth.token}"
```

The delay is applied right before the step runs. If omitted, the step executes immediately.

### Print Response Keys

Optionally print specific values from the response to the console. Useful for seeing IDs or statuses without digging through the CSV:

```yaml
- name: create-lead
  url: "https://api.example.com/lead"
  method: POST
  print_keys:
    - leadId
    - status
  headers:
    Authorization: "Bearer ${auth.token}"

- name: create-application
  url: "https://api.example.com/application"
  method: POST
  print_keys:
    - userId
  payload:
    leadId: "${create-lead.leadId}"
```

This prints after each step's pass/fail line:

```
[2/8] ▶ create-lead running....
         ✅ Passed — HTTP 200 (1205ms)
         📋 leadId = 12345
         📋 status = INITIATED
```

Supports dot-notation for nested keys (e.g. `data.user.id`) and array indices (e.g. `items.-1.name`).

### Cross-Step References

Use `${step_name.key.path}` to reference values from previous step responses:

```yaml
# References auth step's response field "idToken"
Authorization: "Bearer ${auth.idToken}"

# References in URL query params
url: "https://api.example.com/status?id=${create_lead.leadId}"

# References pre-defined variables
Authorization: "Bearer ${vars.my_token}"
```

### Environment Variables

Use `${ENV:VAR_NAME}` in your YAML to reference environment variables. This keeps secrets like API keys and tokens out of your YAML files.

```yaml
variables:
  my_token: "${ENV:MY_TOKEN}"
  firebase_key: "${ENV:FIREBASE_KEY}"

chain:
  - name: auth
    url: "https://api.example.com/auth?key=${ENV:API_KEY}"
    method: POST
    payload:
      email: "${ENV:AUTH_EMAIL}"
```

#### `.env` File (Auto-Loaded)

Create a `.env` file in your project directory with key-value pairs:

```
# .env
MY_TOKEN="eyJhbGciOi..."
FIREBASE_KEY="AIzaSy..."
API_KEY="your-api-key"
AUTH_EMAIL="user@example.com"
```

The `.env` file is auto-discovered from these locations (in order):
1. Same directory as the YAML config file
2. One level up from the config file (project root)
3. Current working directory

No extra flags needed — just place the `.env` file and run:

```bash
# CLI — auto-loads .env
python -m api_chain_runner my_chain.yaml

# UI — auto-loads .env from flow dir and project root
python -m api_chain_runner --ui flow/
```

#### Custom `.env` File

Use `-e` / `--env` to specify a different env file:

```bash
# CLI with custom env file
python -m api_chain_runner my_chain.yaml -e production.env

# UI with custom env file
python -m api_chain_runner --ui flow/ -e staging.env
```

#### Rules

- `.env` values do **not** override existing shell environment variables
- Lines starting with `#` are treated as comments
- Values can be quoted (`"value"` or `'value'`) or unquoted
- If a `${ENV:VAR_NAME}` placeholder can't be resolved, it's left as-is so you get a clear error

### Unique Data Generation

Auto-generate unique values per run to avoid duplicates:

```yaml
payload:
  email: "placeholder"
  pan: "placeholder"
  mobile: "placeholder"
unique_fields:
  email: email        # generates: user_1718901234_a1b2c3@test.com
  pan: pan            # generates: valid Indian PAN format (random entity type)
  mobile: mobile      # generates: 10-digit Indian mobile number
```

You can control the PAN entity type (the 4th character) using a suffix:

| Generator Type | 4th Character | Entity Type |
|---------------|---------------|-------------|
| `pan` | Random from `PCHFAT` | Any |
| `pan-p` | `P` | Individual |
| `pan-c` | `C` | Company |
| `pan-h` | `H` | HUF |
| `pan-f` | `F` | Firm |
| `pan-a` | `A` | AOP |
| `pan-t` | `T` | Trust |

Example:

```yaml
unique_fields:
  pan: pan-p      # always generates Individual PAN (4th char = P)
  pan: pan-c      # always generates Company PAN (4th char = C)
  pan: pan        # random entity type
```

### Custom Generators (Plugin System)

If you're using `python -m api_chain_runner` as a library, you can register your own generator functions. Once registered, they work in YAML `unique_fields` just like the built-in ones.

```python
import random
from api_chain_runner import ChainRunner

runner = ChainRunner("my_chain.yaml")

# Register custom generators
runner.generator.register_generator(
    "name", lambda: random.choice(["Alice", "Bob", "Charlie"])
)
runner.generator.register_generator(
    "city", lambda: random.choice(["Mumbai", "Delhi", "Bangalore"])
)

result = runner.run()
```

Then in your YAML:

```yaml
payload:
  customer_name: "placeholder"
  city: "placeholder"
unique_fields:
  customer_name: name
  city: city
```

Rules:
- The function must take no arguments and return a string.
- You cannot override built-in generators (`email`, `pan`, `mobile`, `udyam`).
- If an unknown generator type is used in YAML without being registered, the runner raises a clear error.

### File Uploads

Upload files as multipart/form-data:

```yaml
- name: upload_doc
  url: "https://api.example.com/upload?id=${prev_step.id}"
  method: POST
  headers:
    Authorization: "Bearer ${auth.token}"
  files:
    file: "path/to/document.pdf"
```

### Polling

Wait for an async operation to complete. Supports negative array indices (`-1` for last element):

```yaml
- name: wait_for_approval
  url: "https://api.example.com/status"
  method: GET
  headers:
    Authorization: "Bearer ${auth.token}"
  polling:
    key_path: "applications.-1.status"   # -1 = last element in the array
    expected_values: ["APPROVED", "COMPLETED"]
    interval: 10          # seconds between retries
    max_timeout: 120      # max wait time in seconds
```

Array index examples in `key_path`:
- `applications.0.status` — first element
- `applications.-1.status` — last element
- `applications.-2.status` — second-to-last element

During polling, only the final result (success or timeout) is logged to CSV. Intermediate attempts are printed to the console with the current value so you can watch the status transition in real time.

### Console Progress Output

When running a chain, you get live step-by-step progress in the terminal:

```
============================================================
  Running chain: phonepe_test_chain (8 steps)
============================================================

[1/8] ▶ auth (POST https://www.googleapis.com/identitytoolkit/v3/...)
         ✅ Passed — HTTP 200 (342ms)
[2/8] ▶ create-lead (POST https://uat-gateway.datasignstech.com/lead/lead)
         ⏳ Waiting 20s before executing...
         ✅ Passed — HTTP 200 (1205ms)
[3/8] ▶ check-status (GET https://uat-gateway.datasignstech.com/lead/status...)
         ⏳ Waiting 20s before executing...
         ❌ Failed — HTTP 500 (89ms)

⛔ Chain aborted at step 'check-status' (continue_on_error=false)

============================================================
  Done: 2 passed, 1 failed out of 3 steps
  Results saved to: phonepe_test_chain_results.csv
============================================================
```

### Pause / Resume During Execution

While a chain is running in the terminal, you can pause and resume execution in real time:

- Press `p` to pause — the runner will pause at the next safe point (between steps or between polling attempts)
- Press `r` or `Enter` to resume

Key behaviors:
- Pause works between steps, during delays, and inside polling loops
- The polling timeout clock freezes while paused
- An in-flight HTTP request will complete before the pause takes effect
- Press `Ctrl+C` to abort the chain entirely

### Manual Steps

Insert a manual checkpoint where the chain pauses and shows instructions. The user must complete a task outside the tool (e.g. fill a form in a browser) and press Enter to continue:

```yaml
- name: generate-link
  url: "https://api.example.com/registration-link"
  method: POST
  payload:
    leadId: "${create-lead.leadId}"
  print_keys:
    - link

- name: complete-registration
  manual: true
  instruction: |
    1. Open the registration link printed above
    2. Fill in the form in your browser
    3. Submit and wait for confirmation
    4. Come back here and press Enter
  print_ref:
    - "generate-link.link"
```

Console output:

```
[8/12] ▶ complete-registration
         ┌──────────────────────────────────────────────────┐
         │  📋 MANUAL STEP                                  │
         │                                                  │
         │  1. Open the registration link printed above     │
         │  2. Fill in the form in your browser             │
         │  3. Submit and wait for confirmation             │
         │  4. Come back here and press Enter               │
         └──────────────────────────────────────────────────┘
         📋 generate-link.link = https://registration.example.com/...
         ⏳ Waiting for you to complete the task...
         Press Enter to continue ▶
```

Manual steps are logged to CSV as `MANUAL — completed by user`.

### Conditional Steps

Only execute a step if a previous step's response matches a specific value. You can use a single condition or multiple conditions (all must pass):

```yaml
# Single condition (operator defaults to equals for backward compatibility)
- name: generate-registration-link
  url: "https://api.example.com/registration-link"
  method: POST
  condition:
    step: check-status
    key_path: "businessProofVerification"
    expected_value: "PENDING"

# List membership — runs only when the value is present in the list
- name: next-step
  url: "https://api.example.com/next"
  method: POST
  condition:
    step: get-lead-status
    key_path: "lead_status"
    operator: contains
    expected_value: "okyc"
  headers:
    Authorization: "Bearer ${auth.token}"
  payload:
    leadId: "${lead.id}"

# Multiple conditions (ALL must pass)
- name: ready-to-sanction
  url: "https://api.example.com/ready-to-sanction"
  method: POST
  condition:
    - step: check-status
      key_path: "kybRemarks.udyamFetchStatus"
      expected_value: "SUCCESS"
    - step: check-status
      key_path: "kybRemarks.udyamFormFilled"
      expected_value: "SUCCESS"
  headers:
    Authorization: "Bearer ${auth.token}"
  payload:
    leadId: "${lead.id}"
```

Conditions support these operators:

- `equals` (default) — exact value match; omitting `operator` preserves existing behavior
- `not_equals` — value does not equal the expected value
- `contains` / `not_contains` — expected value is (or is not) in a list, string, or mapping
- `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal` — numeric or string comparisons
- `starts_with` / `ends_with` — string prefix/suffix checks
- `is_null` / `is_not_null` — check whether the response value is null; expected value may be blank

Multiple conditions are ANDed together. If you need to check whether `okyc` appears anywhere in `lead_status`, use `operator: contains` rather than `eval_condition`; `eval_condition` reports a result but does not control later-step execution.


```
[9/12] ⏭ generate-registration-link — skipped (condition not met: businessProofVerification='COMPLETED', expected 'PENDING')
```

Conditions work on both API steps and manual steps.

### Response Evaluation (eval_keys)

Extract values from a response and evaluate them against a condition. Useful for checking thresholds, matching scores, or validating business logic inline:

```yaml
- name: check-credit-report
  url: "https://api.example.com/credit-report?userId=${app.userId}"
  method: GET
  headers:
    Authorization: "Bearer ${vars.token}"
  eval_keys:
    profile_score: "features.AADHAAR_PROFILE_NAME_MATCH_SCORE"
    pan_score: "features.AADHAAR_PAN_NAME_MATCH_SCORE"
  eval_condition: "profile_score > 0.55 and pan_score > 0.55"
  success_message: "Name match scores are above threshold - SUCCESS"
  failure_message: "Name match scores are below threshold - FAILURE"
```

How it works:
1. `eval_keys` extracts values from the response using dot-notation paths and assigns them to named variables
2. `eval_condition` evaluates a Python expression using those variables
3. Prints `success_message` or `failure_message` based on the result
4. Only the extracted `eval_keys` values (plus the eval result) are logged to CSV — not the full response body. This keeps your output focused on the fields you care about.

Console output:

```
[6/8] ▶ check-credit-report (GET https://api.example.com/credit-report?...)
         ✅ Passed — HTTP 200 (523ms)
         [eval] profile_score = 1 (from features.AADHAAR_PROFILE_NAME_MATCH_SCORE)
         [eval] pan_score = 0.3 (from features.AADHAAR_PAN_NAME_MATCH_SCORE)
         [eval] ❌ FAILURE: Name match scores are below threshold - FAILURE
```

You can use any valid Python comparison in `eval_condition`:
- `score > 0.55` — numeric threshold
- `status == 'APPROVED'` — string equality
- `a > 0.5 and b > 0.5` — compound conditions
- `val is not None and val > 0` — null-safe checks

### IST Timestamps

All timestamps in the CSV/Excel output are recorded in Indian Standard Time (IST, UTC+5:30).

## Web UI

API Chain Runner includes a built-in web dashboard for visualizing, editing, and running your chains from the browser.

```bash
# Launch the UI (scans current directory for YAML flows)
python -m api_chain_runner --ui

# Point to a specific flow directory
python -m api_chain_runner --ui flow/

# Custom port
python -m api_chain_runner --ui flow/ --port 8080
```

This opens a local web server at `http://127.0.0.1:5656` with:

- **Dashboard** — a Drive-style view of your YAML chain files: click through folders, see files that sit outside any folder, and use the search bar (press `/`) to find a flow in any folder. The sidebar shows the same folder tree
- **Flow Visualization** — each chain is rendered as a vertical flowchart with step boxes, method badges (GET/POST/PUT/DELETE), and connector arrows
- **Run from UI** — click "Run Chain" to execute the flow live; each step lights up with pass/fail status and HTTP status codes color-coded (green for 2xx, orange for 4xx, red for 5xx)
- **Step Responses** — after a run, a response table shows every step's status code, duration, and response body with resizable preview
- **Step Editor** — click any step to open a slide-over drawer showing full details (URL, headers, payload, polling config); editable fields can be modified and saved directly back to the YAML file
- **Run Selected Steps** — Ctrl/Cmd+click steps to run only those; a popup asks for the payload and query-param values, with the keys filled in for you
- **Retry Failed Steps** — when a stop-on-fail step fails, a Retry button re-runs it and continues the chain with the existing context
- **Add Step on Hover** — hover any step card to insert a new step right after it (API request or manual step)
- **Step List in the Sidebar** — every step of the open flow is listed with its method; click one to jump to it and open the request panel
- **Request Panel** — a Postman-style window that sends just one step: edit the method, URL, params, headers and body (JSON, form-data with file uploads, or urlencoded), then see the response with highlighted JSON, status, time, size and headers
- **Stop a Run** — a **Stop** button ends the run at the current step (even mid-polling or on a manual step) and shows the report of everything that ran so far, ready to export
- **Live Print Keys** — while a polling step is running, its `print_keys` appear next to the step and refresh after every polling attempt, so you can watch values change before the step finishes
- **Environment Variables Editor** — an **Environment** button at the bottom of the sidebar opens a popup to view, add, edit and delete the variables in your `.env` file
- **API or Manual Steps** — the Add Step drawer lets you pick an API request or a manual step
- **Glass Design** — translucent glass panels over a soft blue background, tuned for both light and dark mode
- **Full YAML Editor** — open the raw YAML editor from the sidebar to edit the entire flow file with syntax-aware editing and save
- **Create New Flows** — click "New Flow" on the dashboard to create a new chain with a name, optional folder, and initial steps
- **Dark / Light Mode** — toggle between dark and light themes; preference is persisted across sessions

#### Retry a failed step

When a step with `continue_on_error: false` (shown as `stop-on-fail`) fails, the chain stops and a **Retry** button appears beside that step. This covers HTTP errors and any other failure, such as an unresolved `${...}` reference. Clicking it re-runs only that step and then carries on with the rest of the chain, using the responses already collected, so earlier steps are not repeated. If the retry fails again, the button reappears.

- The retry reuses the step definitions loaded when the run started. If you edit the YAML after a failure, click **Run Chain** again to pick up the change.
- Starting a new run discards the retry option of the previous one. The server keeps the 10 most recent failed runs.

#### Add a step anywhere

Hover over a step card and an **Add Step** button appears below it. Clicking it opens the new-step drawer and inserts the step directly after that card. At the top of the drawer, **Step type** lets you choose an **API request** or a **Manual step**; the form switches accordingly and keeps the name you typed. A manual step needs an instruction. The first card also shows a button above it, to insert at the start.

#### Run only selected steps

Ctrl/Cmd+click one or more step cards to select them. A numbered badge shows the run order, and the Run button changes to **Run Selected (N)**. Click **Clear selection** or press `Esc` to deselect. A plain click still opens the step drawer.

Clicking **Run Selected** opens a popup listing each selected step's **query params** (read from the `?a=b` part of the URL) and **payload** keys (nested objects and lists included). The keys fill in automatically and each value starts as the one in the YAML. Change only the values you need.

- Values apply to this run only. The YAML file is never changed.
- Typed values keep the original type: a number stays a number, and booleans use a true/false dropdown.
- A value that references a step you did not select (for example `${login.token}`) is highlighted, because that step will not run. Enter a value to use instead.
- Unselected steps are shown as skipped ("Not selected") and are not counted as failures.
- A selected step whose `condition` points at a step that has not run is executed rather than silently skipped. Full runs keep the existing skip behaviour.
- If the popup has nothing to fill in (no query params or payload), the steps run immediately.
- Headers and file uploads are not editable in the popup.

#### Send a single step (request panel)

Click a step in the sidebar's **Steps** list to open a Postman-style request panel for that step. It sends exactly one request, so polling, retries, delays and conditions are ignored. Nothing is written to the YAML; use **Edit step** in the panel header to change the saved step.

- **Request bar:** method dropdown, URL, and **Send** (also `Ctrl/Cmd + Enter` from anywhere in the panel).
- **Params:** the query string as editable rows, kept in sync with the URL in both directions. Untick a row to leave it out without deleting it.
- **Headers:** editable rows with the same on/off checkbox.
- **Body:** choose **None**, **JSON** (with a live validity check and **Beautify**), **Form-data** or **x-www-form-urlencoded**.
  - In **Form-data**, each row is **Text** or **File**. A file row takes a path on your machine, or use **Choose file** to pick one in the browser.
  - Content-Type is set automatically for form bodies, so any `Content-Type` header is ignored.
  - Steps that already use `files:` open in Form-data with their files filled in.
  - If two form fields share a name, only the last one is sent.
- **Response:** a status chip (for example `200 OK`), time and size, a syntax-highlighted body with Wrap and Copy, and a Headers tab (click a row to copy a value). Connection errors appear as an error card.
- **Copy cURL:** copies the request as a ready-to-run cURL command, including `-F` parts for form-data.
- **Resizable:** drag the divider between the request and the response.
- `${ENV:NAME}` placeholders are substituted before sending. `${step.key}` references resolve from the last run of the flow, or from earlier sends in the panel. If one can't be resolved, the panel says so instead of sending, so run the chain first or type a literal value.
- Unique fields (for example email or PAN) are regenerated on every send.

#### Environment variables editor

The **Environment** button at the bottom of the sidebar opens a popup for your `.env` file. It is available on every page.

- Values are hidden by default. Use the eye on a row (or **Show values**) to reveal them, and the copy button to copy one.
- Filter by name, add a variable, edit any name or value, or remove one. Names must use letters, digits and `_` and not start with a digit; duplicates and line breaks in values are flagged and block saving.
- The popup edits the first existing `.env` the runner would load: the flow folder, then its parent, then the current working directory. If more than one exists, a dropdown lets you choose. If none exists, saving creates one in the flow folder with owner-only permissions.
- Comments, blank lines and values you did not change are kept exactly as written.
- Saved values apply to this server straight away, so the next run uses them without a restart. A run that is already in progress is not affected.
- Use any variable in a flow as `${ENV:NAME}`.

#### Network: IPv4 first (CLI and UI)

Connections try IPv4 first and fall back to the normal lookup only if a host has no IPv4 address. On networks that publish IPv6 addresses but cannot route them, this avoids waiting for the connect timeout on each IPv6 address (which could take 90 seconds or more). Set `API_CHAIN_RUNNER_IPV6_FIRST=1` to turn this off.

The UI is a built-in feature of the package — anyone who installs `python -m api_chain_runner` gets it with no extra setup.

## Architecture

```
YAML Config → ChainRunner (orchestrator)
                  ├── ReferenceResolver  — resolves ${step.key} expressions
                  ├── UniqueDataGenerator — generates unique emails/PAN/mobile
                  ├── StepExecutor — makes HTTP requests, handles polling & delay
                  ├── ResponseStore — stores responses for cross-step sharing
                  └── ResultLogger — writes results to CSV/XLSX
```

### Module Breakdown

| Module | Role |
|--------|------|
| `__main__.py` | CLI entry point — parses args, substitutes env vars, kicks off the runner |
| `runner.py` | `ChainRunner` — loads YAML config, initializes components, runs steps sequentially with delay and progress output |
| `executor.py` | `StepExecutor` — resolves references, generates data, executes HTTP calls, handles polling with negative index support |
| `resolver.py` | `ReferenceResolver` — replaces `${step.key.path}` with stored response values |
| `store.py` | `ResponseStore` — in-memory key-value store for cross-step data sharing |
| `generator.py` | `UniqueDataGenerator` — creates unique email, PAN, mobile values; supports custom generators via `register_generator()` |
| `logger.py` | `ResultLogger` — logs all requests/responses to CSV or Excel with IST timestamps |
| `models.py` | Data classes (`StepDefinition`, `StepResult`, `ChainResult`, etc.) and validation |
| `net.py` | IPv4-first connection ordering for `requests`, so unroutable IPv6 addresses do not stall requests |
| `ui/` | Flask web UI: `server.py` (API and run engine), `templates/`, and `static/` (flow, request panel, environment editor, styles) |

### Execution Flow

1. CLI parses args and substitutes `${ENV:...}` placeholders in the YAML
2. `ChainRunner` loads the config, validates steps, and pre-seeds variables into the store
3. For each step in order:
   - Console prints the step name, method, and URL
   - If `delay` is set, waits the specified seconds before proceeding
   - `ReferenceResolver` replaces `${step.key}` tokens with actual values from the store
   - `UniqueDataGenerator` injects fresh unique data into marked fields
   - `StepExecutor` fires the HTTP request (with optional polling/retry)
   - Response is saved to `ResponseStore` for downstream steps
   - Request/response details are logged via `ResultLogger` (IST timestamps)
   - Console prints pass/fail result with HTTP status and timing
4. `ResultLogger.finalize()` writes everything to the output file
5. Console prints a final pass/fail summary with output file path

## Running Tests

```bash
pytest
```

## Requirements

- Python 3.10+
- `requests` — HTTP client
- `pyyaml` — YAML parsing
- `openpyxl` — Excel output (optional, only needed for `-f xlsx`)
- `flask` — Web UI server (only needed for `--ui` mode)
