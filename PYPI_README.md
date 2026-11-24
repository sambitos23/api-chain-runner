# API Chain Runner

A powerful Python CLI tool for executing chained API calls defined in YAML. Each step can reference responses from previous steps, generate unique test data, upload files, poll for expected values, retry on failures, and add delays between steps — all logged to CSV or Excel.

Perfect for API testing, integration testing, workflow automation, and complex multi-step API scenarios.

## Installation

```bash
pip install api-chain-runner
```

## Quick Start

1. Create a YAML config file (e.g. `my_chain.yaml`):

```yaml
chain:
  - name: auth
    url: "https://api.example.com/login"
    method: POST
    headers:
      Content-Type: "application/json"
    payload:
      email: "${ENV:AUTH_EMAIL}"
      password: "${ENV:AUTH_PASSWORD}"

  - name: get_user
    url: "https://api.example.com/user/${auth.userId}"
    method: GET
    headers:
      Authorization: "Bearer ${auth.token}"
```

2. Create a `.env` file:

```
AUTH_EMAIL="user@example.com"
AUTH_PASSWORD="secret"
```

3. Run it:

```bash
api-chain-runner my_chain.yaml
```

That's it. Results are saved to `my_chain_results.csv` by default.

## CLI Usage

```bash
# Basic run
api-chain-runner my_chain.yaml

# Custom output path
api-chain-runner my_chain.yaml -o output/results.csv

# Excel output
api-chain-runner my_chain.yaml -o results.xlsx -f xlsx

# Launch web UI
api-chain-runner --ui flow/

# Custom env file
api-chain-runner my_chain.yaml -e production.env

# Check version
api-chain-runner --version
```

## Programmatic Usage

You can also use it as a Python library:

```python
from api_chain_runner import ChainRunner, ChainResult

runner = ChainRunner("my_chain.yaml")
result: ChainResult = runner.run()

print(f"{result.passed}/{result.total_steps} steps passed")
for step in result.results:
    print(f"  {step.step_name}: HTTP {step.status_code}")
```

## Features

### Cross-Step References

Use `${step_name.key.path}` to pass data between steps:

```yaml
Authorization: "Bearer ${auth.idToken}"
url: "https://api.example.com/status?id=${create_lead.leadId}"
```

### Environment Variables

Keep secrets out of your YAML with `${ENV:VAR_NAME}`:

```yaml
variables:
  my_token: "${ENV:MY_TOKEN}"
  firebase_key: "${ENV:FIREBASE_KEY}"

chain:
  - name: auth
    url: "https://api.example.com/auth?key=${ENV:API_KEY}"
    method: POST
```

Create a `.env` file in your project directory:

```
MY_TOKEN="eyJhbGciOi..."
FIREBASE_KEY="AIzaSy..."
API_KEY="your-api-key"
```

The `.env` file is auto-loaded from the config file's directory, its parent directory, or the current working directory. No extra flags needed.

For a custom env file, use `-e` / `--env`:

```bash
api-chain-runner my_chain.yaml -e production.env
api-chain-runner --ui flow/ -e staging.env
```

Library usage:

```python
runner = ChainRunner("my_chain.yaml")                          # auto-loads .env
runner = ChainRunner("my_chain.yaml", env_file="prod.env")     # custom env file
```

Rules:
- `.env` values don't override existing shell environment variables
- Lines starting with `#` are comments
- Unresolved `${ENV:...}` placeholders are left as-is for clear error messages

### Variables

Define reusable values at the top of your config:

```yaml
variables:
  base_url: "https://api.example.com"
  token: "static-token-value"

chain:
  - name: get_data
    url: "${vars.base_url}/data"
    method: GET
    headers:
      Authorization: "Bearer ${vars.token}"
```

### Retry Configuration

Automatically retry steps that fail due to transient errors:

```yaml
- name: fetch-data
  url: "https://api.example.com/data"
  method: GET
  retry:
    max_attempts: 3      # total attempts (default: 3)
    delay: 2             # seconds between retries (default: 5)
    retry_on:            # error types to retry on
      - timeout
      - connection
      - 5xx
```

Retry types:
- `timeout` — request timed out
- `connection` — connection refused / DNS failure
- `5xx` — server returned 500-599
- `4xx` — server returned 400-499 (use with caution)

To disable retries: `retry: false`

Default behavior: 3 attempts on timeout/connection/5xx errors.

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

### Unique Data Generation

Auto-generate unique emails, PAN numbers, mobile numbers, and UDYAM IDs per run:

```yaml
payload:
  email: "placeholder"
  pan: "placeholder"
  mobile: "placeholder"
  udyam: "placeholder"
unique_fields:
  email: email
  pan: pan
  mobile: mobile
  udyam: udyam
```

You can control the PAN entity type (the 4th character) using a suffix:

| Generator Type | 4th Character | Entity Type |
|---------------|---------------|-------------|
| `pan` | Random | Any |
| `pan-p` | `P` | Individual |
| `pan-c` | `C` | Company |
| `pan-h` | `H` | HUF |
| `pan-f` | `F` | Firm |
| `pan-a` | `A` | AOP |
| `pan-t` | `T` | Trust |

```yaml
unique_fields:
  pan: pan-p      # Individual PAN
  pan: pan-c      # Company PAN
  pan: pan        # random entity type
```

### Custom Generators (Plugin System)

Register your own generator functions when using `api-chain-runner` as a library:

```python
import random
from api_chain_runner import ChainRunner

runner = ChainRunner("my_chain.yaml")
runner.generator.register_generator(
    "name", lambda: random.choice(["Alice", "Bob", "Charlie"])
)
result = runner.run()
```

Then use it in YAML:

```yaml
unique_fields:
  customer_name: name
```

- Function must take no args and return a string.
- Cannot override built-ins (`email`, `pan`, `mobile`, `udyam`).

### Polling

Wait for async operations to complete:

```yaml
polling:
  key_path: "status"
  expected_values: ["APPROVED", "COMPLETED"]
  interval: 10
  max_timeout: 120
```

Supports negative array indices:

```yaml
polling:
  key_path: "applications.-1.status"   # -1 = last element
  expected_values: ["APPROVED"]
  interval: 5
  max_timeout: 60
```

### Delays

Add wait time between steps:

```yaml
- name: check-status
  url: "https://api.example.com/status"
  method: GET
  delay: 20
```

### File Uploads

Upload files as multipart/form-data:

```yaml
files:
  document: "path/to/file.pdf"
```

### Conditional Steps

Condition operators include `equals` (the default), `not_equals`, `contains`, `not_contains`, `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, `starts_with`, `ends_with`, `is_null`, and `is_not_null`. Multiple conditions are ANDed. Use `contains` for list membership; unlike `eval_condition`, a `condition` controls whether the dependent step runs.

```yaml
# Single condition (operator defaults to `equals`)
- name: generate-link
  url: "https://api.example.com/link"
  method: POST
  condition:
    step: check-status
    key_path: "status"
    expected_value: "PENDING"

# List membership
- name: next-step
  url: "https://api.example.com/next"
  method: POST
  condition:
    step: get-lead-status
    key_path: "lead_status"
    operator: contains
    expected_value: "okyc"

# Multiple conditions (ALL must pass)
- name: ready-to-sanction
  url: "https://api.example.com/sanction"
  method: POST
  condition:
    - step: check-status
      key_path: "kyb.udyam"
      expected_value: "SUCCESS"
    - step: check-status
      key_path: "kyb.pan"
      expected_value: "SUCCESS"
```

### Response Evaluation

Extract and evaluate response values against conditions:

```yaml
- name: check-scores
  url: "https://api.example.com/report?userId=${app.userId}"
  method: GET
  eval_keys:
    profile_score: "features.PROFILE_SCORE"
    pan_score: "features.PAN_SCORE"
  eval_condition: "profile_score > 0.55 and pan_score > 0.55"
  success_message: "Scores above threshold - SUCCESS"
  failure_message: "Scores below threshold - FAILURE"
```

Supports any Python comparison: `>`, `==`, `and`, `or`, `is not None`, etc.

### Manual Steps

Pause the chain for manual actions (e.g. filling a form in a browser):

```yaml
- name: complete-registration
  manual: true
  instruction: "Open the link above, fill the form, then press Enter here"
  print_ref:
    - "generate-link.link"
```

### Pause / Resume

Press `p` to pause between steps, `r` or `Enter` to resume, `Ctrl+C` to abort.

### Web UI

API Chain Runner includes a built-in web dashboard for visualizing, editing, and running your chains from the browser.

```bash
# Launch the UI (scans current directory for YAML flows)
api-chain-runner --ui

# Point to a specific flow directory
api-chain-runner --ui flow/

# Custom port
api-chain-runner --ui flow/ --port 8080
```

This opens a local web server at `http://127.0.0.1:5656` with:

- **Dashboard** — a Drive-style view of your YAML chain files: click through folders, see files that sit outside any folder, and use the search bar (press `/`) to find a flow in any folder. The sidebar shows the same folder tree
- **Flow Visualization** — vertical flowchart with method badges, connector arrows, and status indicators
- **Run from UI** — execute flows live with real-time pass/fail status and color-coded HTTP status codes
- **Step Responses** — response table with status, duration, and resizable response body preview
- **Step Editor** — click any step to edit URL, headers, payload directly and save back to the YAML file
- **Run Selected Steps** — Ctrl/Cmd+click steps to run only those; a popup asks for the payload and query-param values, with the keys filled in for you
- **Retry Failed Steps** — when a stop-on-fail step fails, a Retry button re-runs it and continues the chain with the existing context
- **Add Step on Hover** — hover any step card to insert a new step right after it (API request or manual step)
- **Step List in the Sidebar** — every step of the open flow is listed with its method; click one to jump to it and open the request panel
- **Request Panel** — a Postman-style window that sends just one step: edit the method, URL, params, headers and body (JSON, form-data with file uploads, or urlencoded), then see the response with highlighted JSON, status, time, size and headers
- **Environment Variables Editor** — an **Environment** button at the bottom of the sidebar opens a popup to view, add, edit and delete the variables in your `.env` file
- **API or Manual Steps** — the Add Step drawer lets you pick an API request or a manual step
- **Glass Design** — translucent glass panels over a soft blue background, tuned for both light and dark mode
- **Full YAML Editor** — edit the raw YAML with save support
- **Create New Flows** — create new chains from the dashboard with name, folder, and initial steps
- **Dark / Light Mode** — toggle themes with persistent preference

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

No extra setup needed — the UI is included in the package.

## Step Fields Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | string | Unique step identifier |
| `url` | No* | string | Request URL (supports `${step.key}` references) — *required unless `manual: true` |
| `method` | No* | string | HTTP method (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`) — *required unless `manual: true` |
| `headers` | No | dict | Request headers |
| `payload` | No | dict | JSON request body |
| `files` | No | dict | File uploads (`field: path`) |
| `unique_fields` | No | dict | Auto-generate unique values (`path: type`) |
| `polling` | No | object | Retry until response matches expected value |
| `delay` | No | int | Seconds to wait before this step |
| `print_keys` | No | list | Response keys to print to console |
| `manual` | No | bool | Manual checkpoint step |
| `instruction` | No* | string | Instructions for manual steps — *required if `manual: true` |
| `print_ref` | No | list | References to print from previous steps |
| `condition` | No | object/list | Conditional execution (single or multiple) |
| `continue_on_error` | No | bool | Stop chain on failure if `false` |
| `retry` | No | object/bool | Retry configuration for transient failures |
| `eval_keys` | No | dict | Extract response values into named variables |
| `eval_condition` | No | string | Python expression to evaluate using `eval_keys` |
| `success_message` | No | string | Message printed when `eval_condition` is true |
| `failure_message` | No | string | Message printed when `eval_condition` is false |

## Output

Results are logged to CSV or Excel with timestamps, including full request/response details for each step.

```
============================================================
  Running chain: my_chain (3 steps)
============================================================

[1/3] ▶ auth (POST https://api.example.com/login)
         ✅ Passed — HTTP 200 (342ms)
[2/3] ▶ create-lead (POST https://api.example.com/lead)
         ✅ Passed — HTTP 200 (1205ms)
[3/3] ▶ check-status (GET https://api.example.com/status)
         ✅ Passed — HTTP 200 (89ms)

============================================================
  Done: 3 passed, 0 failed out of 3 steps
  Results saved to: my_chain_results.csv
============================================================
```

## Requirements

- Python 3.10+

All dependencies (`requests`, `pyyaml`, `openpyxl`, `flask`) are installed automatically.

## License

MIT
