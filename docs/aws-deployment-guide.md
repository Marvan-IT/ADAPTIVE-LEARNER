# ADA — Complete AWS Deployment Guide (Zero to Live)

This guide takes you from **no AWS account** to a **fully live app** with automatic deployments. Every step is explained for someone who has never used AWS.

**What you'll end up with:**
- ADA running at `https://yourdomain.com` on a $15-30/mo EC2 instance
- Automatic deploys: push to `main` on GitHub → app updates automatically
- SSL/HTTPS via Let's Encrypt (free, auto-renewing)
- PostgreSQL + pgvector running in Docker
- Admin account: `muhammed.marvan@hightekers.com`

**Estimated time:** 60-90 minutes for first-time setup.

---

## Part 1: Create Your AWS Account (10 min)

### Step 1.1 — Sign up
1. Go to https://aws.amazon.com and click **"Create an AWS Account"**
2. Enter your email, choose a password, and pick an account name (e.g., "ADA-Production")
3. Choose **"Personal"** account type
4. Enter your credit card (you won't be charged until you exceed free tier — but the card is required)
5. Complete phone verification
6. Choose **"Basic Support — Free"** plan
7. Sign in to the **AWS Console** at https://console.aws.amazon.com

### Step 1.2 — Set your region
1. In the top-right of the AWS Console, you'll see a region name (e.g., "N. Virginia")
2. Click it and select **US East (N. Virginia) us-east-1** — this is the cheapest region
3. **All steps below assume us-east-1.** Keep this selected throughout.

---

## Part 2: Buy a Domain via Route 53 (5 min)

### Step 2.1 — Register a domain
1. In the AWS Console search bar, type **"Route 53"** and open it
2. Click **"Register domains"** in the left sidebar
3. Click **"Register domains"** button
4. Search for a domain name (e.g., `adalearn.com`, `ada-learn.org`, `yourname-ada.com`)
   - `.com` domains cost ~$13/year
   - `.org` domains cost ~$12/year
   - `.net` domains cost ~$11/year
5. Click **"Select"** next to your preferred domain, then **"Proceed to checkout"**
6. Fill in contact information (this is required by ICANN — you can enable privacy protection)
7. **Enable "Auto-renew"** so you don't lose the domain
8. Complete the purchase

**The domain takes 5-15 minutes to register.** You'll get an email confirmation. Continue with the next steps while waiting.

> **Note your domain name** — I'll refer to it as `YOURDOMAIN.COM` throughout this guide. Replace it everywhere.

---

## Part 3: Create an SSH Key Pair (2 min)

### Step 3.1 — Create key pair in AWS
1. In the AWS Console search bar, type **"EC2"** and open it
2. In the left sidebar, click **"Key Pairs"** (under "Network & Security")
3. Click **"Create key pair"**
4. Settings:
   - **Name:** `ada-key`
   - **Key pair type:** RSA
   - **Private key file format:** `.pem`
5. Click **"Create key pair"**
6. A file called `ada-key.pem` will download. **Save this file somewhere safe!** You cannot download it again.

### Step 3.2 — Set key permissions (on your local machine)
Open a terminal (Git Bash on Windows, Terminal on Mac) and run:
```bash
# Move the key to a safe location
mv ~/Downloads/ada-key.pem ~/.ssh/ada-key.pem

# Set correct permissions (required for SSH to work)
chmod 400 ~/.ssh/ada-key.pem
```

---

## Part 4: Create a Security Group (3 min)

This controls which network traffic can reach your server.

1. In EC2 Console, click **"Security Groups"** in the left sidebar
2. Click **"Create security group"**
3. Settings:
   - **Name:** `ada-security-group`
   - **Description:** `ADA web server - HTTP, HTTPS, SSH`
   - **VPC:** Leave the default VPC selected
4. **Inbound rules** — click "Add rule" for each:

   | Type | Port Range | Source | Description |
   |------|-----------|--------|-------------|
   | SSH | 22 | My IP | SSH access (your current IP) |
   | HTTP | 80 | Anywhere-IPv4 (0.0.0.0/0) | Web traffic (redirects to HTTPS) |
   | HTTPS | 443 | Anywhere-IPv4 (0.0.0.0/0) | Secure web traffic |

5. **Outbound rules:** Leave as default (All traffic, all destinations)
6. Click **"Create security group"**

---

## Part 5: Launch EC2 Instance (5 min)

### Step 5.1 — Launch
1. In EC2 Console, click **"Instances"** in the left sidebar
2. Click **"Launch instances"**
3. Settings:

   **Name:** `ADA-Production`

   **Application and OS Images (AMI):**
   - Select **"Ubuntu"**
   - Choose **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type**
   - Architecture: **64-bit (x86)**

   **Instance type:**
   - Select **t3.small** (2 vCPU, 2 GB RAM — ~$15/month)

   **Key pair:**
   - Select **ada-key** (the one you created in Part 3)

   **Network settings:**
   - Click **"Edit"**
   - **Auto-assign public IP:** Enable
   - **Select existing security group:** choose `ada-security-group`

   **Configure storage:**
   - Change root volume to **30 GB** gp3 (enough for Docker images, extracted textbooks, and database)

4. Click **"Launch instance"**
5. Click on the instance ID link to view it

### Step 5.2 — Allocate an Elastic IP (static IP)
Without this, your IP changes every time the instance restarts.

1. In EC2 Console, click **"Elastic IPs"** in the left sidebar
2. Click **"Allocate Elastic IP address"**
3. Click **"Allocate"**
4. Select the new Elastic IP, click **"Actions"** → **"Associate Elastic IP address"**
5. Select your `ADA-Production` instance
6. Click **"Associate"**

> **Write down your Elastic IP** (e.g., `54.123.45.67`). You'll need it for DNS and SSH.

### Step 5.3 — Point your domain to the EC2 instance
1. Go to **Route 53** in the AWS Console
2. Click **"Hosted zones"** → click your domain name
3. Click **"Create record"**
4. Settings:
   - **Record name:** leave empty (this creates the root record for `YOURDOMAIN.COM`)
   - **Record type:** A
   - **Value:** paste your Elastic IP (e.g., `54.123.45.67`)
   - **TTL:** 300
5. Click **"Create records"**

DNS propagation takes 5-30 minutes. You can check with:
```bash
nslookup YOURDOMAIN.COM
```

---

## Part 6: Connect to Your Server via SSH (2 min)

Open a terminal (Git Bash on Windows, Terminal on Mac):

```bash
ssh -i ~/.ssh/ada-key.pem ubuntu@YOUR_ELASTIC_IP
```

If you see `Are you sure you want to continue connecting?`, type `yes`.

You should now see:
```
ubuntu@ip-xxx-xxx-xxx-xxx:~$
```

**You're now logged into your AWS server!** All commands below run on this server.

---

## Part 7: Install Docker on the Server (3 min)

Run these commands on the EC2 instance:

```bash
# Update system packages
sudo apt-get update -y && sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow your user to run Docker without sudo
sudo usermod -aG docker ubuntu

# Apply group change (or log out and back in)
newgrp docker

# Verify Docker works
docker --version
docker compose version
```

---

## Part 8: Clone the Repository (2 min)

```bash
cd /home/ubuntu

# Clone your repo (use HTTPS — simpler for first setup)
git clone https://github.com/YOUR_GITHUB_USERNAME/ADA.git

cd ADA
```

> Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username.

---

## Part 9: Configure Environment Files (10 min)

### Step 9.1 — Create the root `.env` file
```bash
cd /home/ubuntu/ADA

cat > .env << 'ROOTEOF'
# ── PostgreSQL ───────────────────────────────────────────────────
POSTGRES_PASSWORD=CHANGE_ME_STRONG_DB_PASSWORD_HERE

# ── Domain (used by deploy.sh and CI/CD to generate nginx.conf) ──
DOMAIN=YOURDOMAIN.COM

# ── Domain & URLs ────────────────────────────────────────────────
FRONTEND_URL=https://YOURDOMAIN.COM
IMAGE_BASE_URL=https://YOURDOMAIN.COM/images

# ── Frontend Build Args ──────────────────────────────────────────
VITE_API_SECRET_KEY=CHANGE_ME_API_SECRET_HERE
VITE_POSTHOG_KEY=
ROOTEOF
```

**Now edit the file and replace the placeholder values:**
```bash
nano .env
```

Generate strong random values:
```bash
# Generate a strong database password (copy the output)
openssl rand -hex 16

# Generate an API secret key (copy the output — you'll use this in BOTH root .env and backend .env)
openssl rand -hex 32
```

Replace:
- `CHANGE_ME_STRONG_DB_PASSWORD_HERE` → paste the 16-char hex from first command
- `CHANGE_ME_API_SECRET_HERE` → paste the 32-char hex from second command
- `YOURDOMAIN.COM` → your actual domain (e.g., `adalearn.com`)

Save: press `Ctrl+O`, `Enter`, then `Ctrl+X`.

### Step 9.2 — Create the backend `.env` file
```bash
cat > backend/.env << 'BACKEOF'
# ── OpenAI ───────────────────────────────────────────────────────
OPENAI_API_KEY=sk-YOUR_OPENAI_KEY_HERE
OPENAI_MODEL=gpt-4o
OPENAI_MODEL_MINI=gpt-4o-mini

# ── Mathpix (optional — only needed for PDF extraction pipeline)
MATHPIX_APP_ID=
MATHPIX_APP_KEY=

# ── Database (overridden by docker-compose, but needed for alembic CLI)
DATABASE_URL=postgresql+asyncpg://postgres:SAME_DB_PASSWORD_AS_ROOT_ENV@localhost:5432/AdaptiveLearner

# ── Security ─────────────────────────────────────────────────────
API_SECRET_KEY=SAME_API_SECRET_AS_ROOT_ENV
JWT_SECRET_KEY=CHANGE_ME_JWT_SECRET_HERE

# ── Environment ──────────────────────────────────────────────────
ENVIRONMENT=production
FRONTEND_URL=https://YOURDOMAIN.COM

# ── Email (SMTP) — required for OTP verification ─────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your.email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
SMTP_FROM=your.email@gmail.com

# ── Image serving ────────────────────────────────────────────────
IMAGE_BASE_URL=https://YOURDOMAIN.COM/images
BACKEOF
```

**Edit and replace all placeholders:**
```bash
nano backend/.env
```

Generate the JWT secret:
```bash
openssl rand -hex 32
```

Replace:
- `sk-YOUR_OPENAI_KEY_HERE` → your actual OpenAI API key (get from https://platform.openai.com/api-keys)
- `SAME_DB_PASSWORD_AS_ROOT_ENV` → the same database password you used in root `.env`
- `SAME_API_SECRET_AS_ROOT_ENV` → the same API secret you used in root `.env`
- `CHANGE_ME_JWT_SECRET_HERE` → paste the 32-char hex from the command above
- `YOURDOMAIN.COM` → your actual domain (2 places)
- SMTP fields → your email credentials (see box below)

> **Setting up Gmail SMTP for OTP emails:**
> 1. Go to https://myaccount.google.com/security
> 2. Enable **2-Step Verification** if not already enabled
> 3. Go to https://myaccount.google.com/apppasswords
> 4. Create an app password for "Mail" → "Other" (name it "ADA")
> 5. Copy the 16-character password
> 6. Use your Gmail address as `SMTP_USER` and `SMTP_FROM`
> 7. Use the app password as `SMTP_PASSWORD`

### Step 9.3 — Lock down file permissions
```bash
chmod 600 .env backend/.env
```

---

## Part 10: Deploy the Application (10 min)

### Step 10.1 — Generate nginx.conf and SSL certificate
```bash
cd /home/ubuntu/ADA

# Make deploy script executable
chmod +x deploy.sh

# Run the deployment script with your domain and email
./deploy.sh YOURDOMAIN.COM muhammed.marvan@hightekers.com
```

This script will:
1. Generate `frontend/nginx.conf` from the template
2. Create a temporary self-signed certificate
3. Start nginx to pass the Let's Encrypt HTTP challenge
4. Get a real SSL certificate from Let's Encrypt
5. Build and start all Docker containers
6. Run database migrations

**Wait for it to finish.** You should see:
```
=========================================
  ADA deployed successfully!
  https://YOURDOMAIN.COM
=========================================
```

### Step 10.2 — Verify everything is running
```bash
# Check all containers are up
docker compose ps

# You should see:
#   ada-db-1        running (healthy)
#   ada-backend-1   running
#   ada-frontend-1  running
#   ada-certbot-1   running

# Check backend health
curl -s http://localhost:8889/health | python3 -m json.tool

# You should see:
# {
#     "status": "ok",
#     "chunk_count": 0    <-- 0 is normal, no textbooks loaded yet
# }

# Check logs for errors
docker compose logs backend --tail 50
```

### Step 10.3 — Test in your browser
Open `https://YOURDOMAIN.COM` in your browser. You should see the ADA login page!

---

## Part 11: Create Your Admin Account (2 min)

```bash
cd /home/ubuntu/ADA

# Run the admin seed script inside the backend container
docker compose exec backend python -m scripts.seed_admin \
  --email muhammed.marvan@hightekers.com \
  --password "YourStrongPassword123!"
```

Replace `YourStrongPassword123!` with a strong password that has:
- At least 8 characters
- One uppercase letter
- One lowercase letter
- One number

You should see:
```
Admin user created successfully: muhammed.marvan@hightekers.com
```

**Now go to `https://YOURDOMAIN.COM` and log in with your admin email and password.** You'll be taken to the admin console.

---

## Part 12: Set Up Automatic Deployments (CI/CD) (5 min)

Every time you push to `main` on GitHub, the app will automatically update on the server.

### Step 12.1 — Add SSH key to GitHub Secrets
1. On your **local machine**, read the SSH key content:
   ```bash
   cat ~/.ssh/ada-key.pem
   ```
2. Copy the ENTIRE output (including `-----BEGIN RSA PRIVATE KEY-----` and `-----END RSA PRIVATE KEY-----`)
3. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**
4. Click **"New repository secret"** and add these 4 secrets:

   | Name | Value |
   |------|-------|
   | `EC2_HOST` | Your Elastic IP (e.g., `54.123.45.67`) |
   | `EC2_USER` | `ubuntu` |
   | `EC2_SSH_KEY` | The full content of `ada-key.pem` (copied in step 1) |
   | `EC2_PROJECT_PATH` | `/home/ubuntu/ADA` |

### Step 12.2 — Test the pipeline
1. Make any small change to a file in your local repo
2. Commit and push to `main`:
   ```bash
   git add .
   git commit -m "test: verify CI/CD pipeline"
   git push origin main
   ```
3. Go to your GitHub repo → **Actions** tab
4. You should see a workflow running with 3 jobs:
   - **Backend — Lint** (ruff check)
   - **Frontend — Build** (npm build)
   - **Backend — Test** (pytest)
5. After all 3 pass, **Deploy — EC2** will run automatically
6. Within 2-3 minutes, your live app will be updated!

### Step 12.3 — Verify auto-deploy worked
```bash
# SSH into your server
ssh -i ~/.ssh/ada-key.pem ubuntu@YOUR_ELASTIC_IP

# Check the latest commit matches what you pushed
cd /home/ubuntu/ADA
git log --oneline -1
```

---

## Part 13: Load Your First Textbook (Optional)

To have actual content for students to learn:

### Step 13.1 — Upload a textbook PDF
```bash
cd /home/ubuntu/ADA

# Create the data directory
mkdir -p backend/data

# Copy your textbook PDF into the data directory
# Example: if you have a Prealgebra PDF
# scp -i ~/.ssh/ada-key.pem local-path/Prealgebra.pdf ubuntu@YOUR_IP:/home/ubuntu/ADA/backend/data/
```

### Step 13.2 — Run the extraction pipeline
```bash
# Run the pipeline inside the backend container
docker compose exec backend python -m src.pipeline --book prealgebra
```

This will:
1. Parse the PDF
2. Extract text, headings, and math content
3. Create concept chunks with embeddings (via OpenAI API)
4. Build the prerequisite graph
5. Store everything in PostgreSQL

**This takes 15-60 minutes** depending on the book size and your OpenAI rate limits.

### Step 13.3 — Verify content loaded
```bash
# Check chunk count
curl -s http://localhost:8889/health | python3 -m json.tool
# chunk_count should now be > 0

# Check from admin console
# Go to https://YOURDOMAIN.COM and navigate to Admin > Content
```

---

## Part 14: Image Storage & Serving

Extracted textbook images are stored in `backend/output/{book_slug}/mathpix_extracted/` and served via nginx.

### How it works
- Backend serves images at `/images/{book_slug}/{image_path}`
- nginx proxies `/images/` to the backend container
- The `IMAGE_BASE_URL` env var tells the frontend where to find images
- Docker volume mount (`./backend/output:/app/output`) makes images available inside the container

### Verify images work
After running the extraction pipeline:
```bash
# List extracted images
ls backend/output/prealgebra/mathpix_extracted/ | head

# Test image serving
curl -I https://YOURDOMAIN.COM/images/prealgebra/some-image.png
# Should return HTTP 200
```

---

## Troubleshooting

### "Permission denied" when SSHing
```bash
chmod 400 ~/.ssh/ada-key.pem
```

### Containers won't start
```bash
# Check logs
docker compose logs --tail 100

# Restart everything
docker compose down
docker compose up --build -d

# Re-run migrations
docker compose exec backend python -m alembic upgrade head
```

### SSL certificate fails
```bash
# Make sure DNS is pointing to your Elastic IP
nslookup YOURDOMAIN.COM

# Make sure port 80 is open (check security group)
# Re-run certbot manually
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email muhammed.marvan@hightekers.com \
  --agree-tos --no-eff-email \
  -d YOURDOMAIN.COM
```

### Backend returns 503 on health check
```bash
# Database might not be ready
docker compose logs db --tail 20

# Wait for health check to pass
docker compose exec db pg_isready -U postgres
```

### "OPENAI_API_KEY is not set" error
```bash
# Check backend env is loaded
docker compose exec backend env | grep OPENAI

# If empty, check backend/.env exists and has the key
cat backend/.env | grep OPENAI
```

### Migrations fail
```bash
# Check current migration state
docker compose exec backend python -m alembic current

# Run migrations explicitly
docker compose exec backend python -m alembic upgrade head
```

### Images not showing in cards
```bash
# Verify the IMAGE_BASE_URL is set correctly
docker compose exec backend env | grep IMAGE_BASE_URL
# Should show: https://YOURDOMAIN.COM/images

# Verify the output directory is mounted
docker compose exec backend ls /app/output/

# Test image URL directly in browser
# https://YOURDOMAIN.COM/images/prealgebra/mathpix_extracted/some-image.png
```

### CI/CD deploy fails
1. Check GitHub Actions tab for error details
2. Verify all 4 secrets are set correctly (EC2_HOST, EC2_USER, EC2_SSH_KEY, EC2_PROJECT_PATH)
3. Make sure the EC2 security group allows SSH (port 22) from GitHub's IP ranges
   - Simpler fix: change SSH inbound rule source from "My IP" to "Anywhere-IPv4" temporarily

---

## Monthly Cost Breakdown

| Resource | Cost/Month |
|----------|-----------|
| EC2 t3.small (on-demand) | ~$15 |
| EBS 30 GB gp3 | ~$2.40 |
| Elastic IP (while instance is running) | $0 |
| Route 53 hosted zone | $0.50 |
| Domain registration | ~$1/mo (billed yearly) |
| Data transfer (first 100 GB/mo) | $0 (free tier) |
| **Total** | **~$19/month** |

> **Cost saving tip:** After your first month, consider buying a 1-year Reserved Instance for t3.small — it drops the price to ~$9/month (40% savings).

---

## Security Checklist

After deployment, verify these:

- [ ] `.env` files have `chmod 600` (only owner can read)
- [ ] SSH key has `chmod 400`
- [ ] Security group SSH is restricted to your IP (not open to world)
- [ ] All secrets are random hex strings (not default values)
- [ ] HTTPS is working (padlock icon in browser)
- [ ] Admin login works
- [ ] OTP emails are being sent (test student registration)

---

## Quick Reference Commands

```bash
# SSH into server
ssh -i ~/.ssh/ada-key.pem ubuntu@YOUR_ELASTIC_IP

# View running containers
docker compose ps

# View logs (live)
docker compose logs -f

# View backend logs only
docker compose logs -f backend

# Restart everything
docker compose down && docker compose up -d

# Rebuild and restart (after code changes)
docker compose up --build -d backend frontend

# Run migrations
docker compose exec backend python -m alembic upgrade head

# Create admin user
docker compose exec backend python -m scripts.seed_admin --email EMAIL --password PASSWORD

# Check app health
curl -s https://YOURDOMAIN.COM/health | python3 -m json.tool

# Check disk usage
df -h

# Check memory usage
free -h
```
