# API Chain Runner

A Python CLI tool for executing chained API calls defined in YAML. Each step can reference responses from previous steps, generate unique test data, upload files, poll for expected values, and add delays between steps — all logged to CSV or Excel.

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

2. Run it:

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

### Unique Data Generation

Auto-generate unique emails, PAN numbers, and mobile numbers per run:

```yaml
payload:
  email: "placeholder"
  pan: "placeholder"
  mobile: "placeholder"
unique_fields:
  email: email
  pan: pan
  mobile: mobile
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

Skip steps based on previous responses:

```yaml
condition:
  step: check-status
  key_path: "status"
  expected_value: "PENDING"
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

- **Dashboard** — lists all discovered YAML chain files with step counts and folder grouping
- **Flow Visualization** — vertical flowchart with method badges, connector arrows, and status indicators
- **Run from UI** — execute flows live with real-time pass/fail status and color-coded HTTP status codes
- **Step Responses** — response table with status, duration, and resizable response body preview
- **Step Editor** — click any step to edit URL, headers, payload directly and save back to the YAML file
- **Full YAML Editor** — edit the raw YAML with save support
- **Create New Flows** — create new chains from the dashboard with name, folder, and initial steps
- **Dark / Light Mode** — toggle themes with persistent preference

No extra setup needed — the UI is included in the package.

## Step Fields Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique step identifier |
| `url` | Yes | Request URL (supports `${step.key}` references) |
| `method` | Yes | HTTP method (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS`) |
| `headers` | No | Request headers |
| `payload` | No | JSON request body |
| `files` | No | File uploads (`field: path`) |
| `unique_fields` | No | Auto-generate unique values (`path: type`) |
| `polling` | No | Retry until response matches expected value |
| `delay` | No | Seconds to wait before this step |
| `print_keys` | No | Response keys to print to console |
| `manual` | No | Manual checkpoint step |
| `instruction` | No | Instructions for manual steps |
| `condition` | No | Conditional execution |
| `continue_on_error` | No | Stop chain on failure if `false` |
| `eval_keys` | No | Extract response values into named variables |
| `eval_condition` | No | Python expression to evaluate using `eval_keys` |
| `success_message` | No | Message printed when `eval_condition` is true |
| `failure_message` | No | Message printed when `eval_condition` is false |

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
