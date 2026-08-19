# AGENTS & DEVELOPER OPERATIONAL HANDBOOK
## Shopify Background Remover

> **ATTENTION ALL AI AGENTS & DEVELOPERS:**
> This file is your operational handbook for the Shopify Background Remover project (`shopify-tools/bg-remover/`).
> It details environment setup, local execution, infrastructure provisioning, GitHub Actions deployment workflows, secret management, and maintenance guidelines.

---

## 🚀 1. Local Development & Installation Setup

### Prerequisites
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (Python package manager)
- [`ngrok`](https://ngrok.com/) (For receiving live Shopify webhooks locally)
- [Terraform](https://www.terraform.io/) (>= 1.5.0, for GCP infrastructure provisioning)
- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk)

### Quickstart Setup Commands

```bash
# 1. Install dependencies using uv
uv pip install -r shopify-tools/bg-remover/requirements.txt

# 2. Run unit test suite
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run pytest shopify-tools/bg-remover/tests

# 3. Start local Functions Framework server (runs Receiver on http://localhost:8080)
PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run python3 shopify-tools/bg-remover/run_local_server.py
```

### Local Testing with Live Shopify Webhooks
```bash
# In a separate terminal window, start ngrok tunnel
ngrok http 8080
```
- Copy the HTTPS `ngrok` URL (e.g., `https://xxxx.ngrok-free.app`).
- Set this URL in **Shopify Admin** $\rightarrow$ **Settings** $\rightarrow$ **Notifications** $\rightarrow$ **Webhooks** (`products/update`).

---

## ☁️ 2. GCP Infrastructure Provisioning (Terraform)

GCP infrastructure (Cloud Tasks Queue, Firestore Database, Secret Manager secrets, IAM Service Accounts) is provisioned via Terraform located in `shopify-tools/bg-remover/terraform/`.

### Initial Infrastructure Setup Step-by-Step

```bash
# 1. Authenticate gcloud CLI locally for Terraform
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID

# 2. Configure variables file
cd shopify-tools/bg-remover/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
gcp_project_id             = "your-gcp-project-id"
gcp_region                 = "us-central1"
github_owner               = "yzats"
github_repo_name           = "mzbl"
shopify_webhook_secret     = "your_webhook_secret"
shopify_admin_access_token = "shpat_your_token"
rembg_api_key              = "your_rembg_key"
```

### GitHub PAT & Secret Automation

To allow Terraform to automatically populate GitHub Repository Secrets (`GCP_PROJECT_ID` and `GCP_SA_KEY`):

1. Generate a **Fine-Grained Personal Access Token (PAT)** in GitHub:
   - Go to GitHub $\rightarrow$ **Settings** $\rightarrow$ **Developer Settings** $\rightarrow$ **Personal access tokens** $\rightarrow$ **Fine-grained tokens** $\rightarrow$ **Generate new token**.
   - Select repository `mzbl`.
   - Set **Repository Permissions** $\rightarrow$ **Secrets** $\rightarrow$ **Access: Read and write**.
2. Export the PAT in your terminal:
   ```bash
   export GITHUB_TOKEN="github_pat_..."
   ```
3. Run Terraform:
   ```bash
   terraform init
   terraform apply
   ```

---

## 🔐 3. How GitHub Secrets & Token Expiration Work

### How GitHub Secrets Are Populated
During `terraform apply`, Terraform creates the GCP Service Account (`github-deployer`), generates its private key JSON, and uses your `GITHUB_TOKEN` to write two secrets directly to repository `yzats/mzbl`:
- `GCP_PROJECT_ID`
- `GCP_SA_KEY`

### What Happens When the GitHub Token Expires?
- **Existing Deployments & Workflows:** **NOT AFFECTED.** GitHub Actions uses the persistent `GCP_SA_KEY` secret already stored in repository settings. GitHub Actions workflows will continue to work indefinitely even after your local PAT expires.
- **Future Terraform Infrastructure Modifications:** If you need to re-run `terraform apply` in the future to change infrastructure config *and* the PAT has expired, simply generate a new PAT in GitHub settings and re-export `export GITHUB_TOKEN="github_pat_new..."`.

---

## 🚀 4. Production Deployment Workflow (GitHub Actions)

Deployments are strictly **manual** and separate from automated testing.

### Workflow Files in `.github/workflows/`:
1. **`shopify-bg-remover-test.yml`**:
   - Runs `pytest` unit tests automatically on every `push` or `pull_request` to any branch whenever files under `shopify-tools/bg-remover/` change.
2. **`shopify-bg-remover-deploy.yml`**:
   - Triggered **manually** via `workflow_dispatch`.

### How to Deploy to GCP Production Manually
1. Go to GitHub Repository (`yzats/mzbl`) $\rightarrow$ **Actions** tab.
2. Click **Deploy Shopify Background Remover to GCP** on the left sidebar.
3. Click **Run workflow** dropdown $\rightarrow$ Select `main` branch $\rightarrow$ Click **Run workflow**.

The workflow runs `shopify-tools/bg-remover/deploy_gcp.sh` to build and deploy `shopify_webhook_receiver` and `bg_remover_worker` v2 Cloud Functions on GCP.

---

## 🛠️ 5. Maintenance Guidelines & Agent Rules

Whenever modifying files in `shopify-tools/bg-remover/`:

1. **Always Run Tests Before Committing:**
   ```bash
   PYTHONPATH=shopify-tools/bg-remover:shopify-tools uv run pytest shopify-tools/bg-remover/tests
   ```
2. **Keep `ARCHITECTURE.md` Synchronized:**
   - If changing method signatures, error handling, status code mappings, GraphQL queries, or queue strategies, update `ARCHITECTURE.md` immediately in the same commit.
3. **Never Commit Secrets:**
   - Secrets belong in `config.py` (git-ignored), `terraform.tfvars` (git-ignored), or GCP Secret Manager.
