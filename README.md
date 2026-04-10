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
# Single condition
- name: generate-registration-link
  url: "https://api.example.com/registration-link"
  method: POST
  condition:
    step: check-status
    key_path: "businessProofVerification"
    expected_value: "PENDING"
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

If any condition is not met, the step is skipped with a message:

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

- **Dashboard** — lists all discovered YAML chain files in a card grid, with step counts and folder grouping
- **Flow Visualization** — each chain is rendered as a vertical flowchart with step boxes, method badges (GET/POST/PUT/DELETE), and connector arrows
- **Run from UI** — click "Run Chain" to execute the flow live; each step lights up with pass/fail status and HTTP status codes color-coded (green for 2xx, orange for 4xx, red for 5xx)
- **Step Responses** — after a run, a response table shows every step's status code, duration, and response body with resizable preview
- **Step Editor** — click any step to open a slide-over drawer showing full details (URL, headers, payload, polling config); editable fields can be modified and saved directly back to the YAML file
- **Full YAML Editor** — open the raw YAML editor from the sidebar to edit the entire flow file with syntax-aware editing and save
- **Create New Flows** — click "New Flow" on the dashboard to create a new chain with a name, optional folder, and initial steps
- **Dark / Light Mode** — toggle between dark and light themes; preference is persisted across sessions

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
