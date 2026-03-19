# API Chain Runner

A Python CLI tool for executing chained API calls defined in YAML. Each step can reference responses from previous steps, generate unique test data, upload files, poll for expected values, and add delays between steps — all logged to CSV or Excel with IST timestamps.

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

## Usage

```bash
# Default output: <config_name>_results.csv
python -m api_chain_runner my_chain.yaml

# Custom output path
python -m api_chain_runner my_chain.yaml -o output/results.csv

# Excel output
python -m api_chain_runner my_chain.yaml -o results.xlsx -f xlsx
```

## YAML Chain Format

A chain config has an optional `variables` block and a required `chain` list of steps:

```yaml
variables:
  my_token: "some-static-token"

chain:
  - name: auth
    url: "https://api.example.com/login"
    method: POST
    headers:
      Content-Type: "application/json"
    payload:
      email: "user@example.com"
      password: "secret"

  - name: get_user
    url: "https://api.example.com/user"
    method: GET
    delay: 5
    headers:
      Authorization: "Bearer ${auth.token}"
```

### Step Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique step identifier, used for referencing responses |
| `url` | Yes | Request URL (supports `${step.key}` references) |
| `method` | Yes | HTTP method (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`) |
| `headers` | No | Request headers as key-value pairs |
| `payload` | No | JSON request body |
| `files` | No | File uploads as `field_name: file_path` pairs (multipart/form-data) |
| `unique_fields` | No | Auto-generate unique values — `dotted.path: type` where type is `email`, `pan`, or `mobile` |
| `extract` | No | Extract values from response |
| `polling` | No | Retry until a response field matches an expected value |
| `delay` | No | Seconds to wait before executing this step (default: `0`) |
| `print_keys` | No | List of response key paths to print to console after execution |
| `manual` | No | If `true`, this is a manual step — no HTTP call, just shows instructions |
| `instruction` | No* | Text shown to the user during a manual step (*required if `manual: true`) |
| `print_ref` | No | List of `step.key` references to print from previous steps (for manual steps) |
| `condition` | No | Only execute this step if a previous step's response matches a value |
| `continue_on_error` | No | If `false`, chain stops on failure (default: `true`) |

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

Use `${ENV:VAR_NAME}` in your YAML to pull from environment variables:

```yaml
url: "https://api.example.com/auth?key=${ENV:API_KEY}"
payload:
  email: "${ENV:AUTH_EMAIL}"
```

### Unique Data Generation

Auto-generate unique values per run to avoid duplicates:

```yaml
payload:
  email: "placeholder"
  pan: "placeholder"
  mobile: "placeholder"
unique_fields:
  email: email        # generates: user_1718901234_a1b2c3@test.com
  pan: pan            # generates: valid Indian PAN format
  mobile: mobile      # generates: 10-digit Indian mobile number
```

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

### IST Timestamps

All timestamps in the CSV/Excel output are recorded in Indian Standard Time (IST, UTC+5:30).

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
| `generator.py` | `UniqueDataGenerator` — creates unique email, PAN, and mobile values |
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
