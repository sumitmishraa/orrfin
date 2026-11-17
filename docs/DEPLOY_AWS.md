# Put the Orrfin demo on AWS (Step 28)

This gives you a private demo link such as **https://13-233-10-20.sslip.io** (or **https://demo.orrfin.ai**
if you control that domain). It takes about 45 minutes the first time, mostly waiting.

**What you get:** one server in Mumbai running the whole demo:
- the web app and the API;
- the background worker;
- the database;
- free HTTPS.

The demo uses synthetic data only. It contains no real company, money or ERP.

**What it costs:** about **US$40 a month (around ₹3,400)** while the server runs.
- Server (t3.medium): about $33.
- 30 GB disk: about $3.
- Public IP address: about $4.

Stop the server when you're not demoing and the server part drops to $0 (the disk and IP keep costing about $7).
Set a budget alert in Part A so nothing surprises you.

---

## Part A. Make the AWS account safe (10 minutes, once)

1. Sign in to **https://console.aws.amazon.com** with your root email.
2. Top right, click your name → **Security credentials** → **Assign MFA device** → follow the steps with an
   authenticator app.
3. Search bar → **IAM** → **Users** → **Create user**:
   - name `orrfin-admin`;
   - tick *Provide user access to the AWS Management Console*;
   - attach the policy **AdministratorAccess**;
   - create it, then add MFA for this user too.
4. From now on, sign in as `orrfin-admin`, not root.
5. Search bar → **Billing and Cost Management** → **Budgets** → **Create budget**:
   - *Monthly cost budget*, $50;
   - your email for the alerts.
6. Top right, the region menu → choose **Asia Pacific (Mumbai) ap-south-1**. Every step below happens in Mumbai.

## Part B. A role that lets you open the server from the browser (3 minutes, once)

This replaces SSH keys: you'll open a terminal on the server from the AWS website, and the server keeps no
SSH port open to the internet.

1. Search bar → **IAM** → **Roles** → **Create role**.
2. *Trusted entity type*: **AWS service**. *Use case*: **EC2** → **Next**.
3. Search and tick **AmazonSSMManagedInstanceCore** → **Next**.
4. Role name `orrfin-ec2-role` → **Create role**.

## Part C. Create the server (10 minutes)

1. Search bar → **EC2** → **Launch instance**.
2. **Name:** `orrfin-demo`.
3. **Application and OS image:** **Ubuntu** → **Ubuntu Server 24.04 LTS** (64-bit x86).
4. **Instance type:** **t3.medium** (2 CPUs, 4 GB). The smaller t3.small also works, but the first build is slow.
5. **Key pair:** choose **Proceed without a key pair**, because you'll use the browser terminal from Part B.
6. **Network settings** → **Edit**:
   - *Create security group*, name `orrfin-web-sg`.
   - **Remove** the SSH rule.
   - **Add** a rule: *Type* **HTTP**, *Source* **Anywhere (0.0.0.0/0)**.
   - **Add** a rule: *Type* **HTTPS**, *Source* **Anywhere (0.0.0.0/0)**.
7. **Configure storage:** change 8 GB to **30** GB, type **gp3**.
8. **Advanced details** → **IAM instance profile:** choose **orrfin-ec2-role**.
9. Click **Launch instance**, then **View all instances**. Wait until *Instance state* says **Running**.

## Part D. Give it a fixed address (3 minutes)

Do this **before** the first deploy, because the demo link is built from this address.

1. EC2 left menu → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**.
2. Tick the new address → **Actions** → **Associate Elastic IP address** → *Instance* **orrfin-demo** → **Associate**.
3. Write the address down (for example `13.233.10.20`). Your demo link will be `https://13-233-10-20.sslip.io`.

## Part E. Open a terminal on the server (2 minutes)

1. EC2 → **Instances** → tick **orrfin-demo** → **Connect** (top right) → tab **Session Manager** → **Connect**.
   If the tab says the instance isn't connected yet, wait 2 minutes and refresh: the role from Part B needs a
   moment.
2. A black terminal opens in the browser. Type the line below and press Enter. You are now the server's administrator.
   ```
   sudo -i
   ```

## Part F. Get the code from GitHub (5 minutes)

Your repository `sumitmishraa/orrfin` is private, so the server needs a read-only key of its own.

1. In the server terminal, paste:
   ```
   apt-get update -y && apt-get install -y git
   ssh-keygen -t ed25519 -f /root/.ssh/orrfin_deploy -N "" -C orrfin-demo-server
   cat /root/.ssh/orrfin_deploy.pub
   ```
2. Copy the line that starts with `ssh-ed25519`.
3. On GitHub, add it as a read-only key:
   - open **https://github.com/sumitmishraa/orrfin** → **Settings** → **Deploy keys** → **Add deploy key**;
   - Title `orrfin-demo-server`;
   - paste the key and leave **Allow write access** unticked;
   - click **Add key**.
4. Back in the server terminal:
   ```
   export GIT_SSH_COMMAND="ssh -i /root/.ssh/orrfin_deploy -o StrictHostKeyChecking=accept-new"
   git clone --branch platform-v3 git@github.com:sumitmishraa/orrfin.git /opt/orrfin
   cd /opt/orrfin
   git config core.sshCommand "ssh -i /root/.ssh/orrfin_deploy"
   ```

## Part G. Deploy (10–15 minutes, mostly waiting)

```
cd /opt/orrfin
bash infra/deploy.sh
```

The script runs these steps (watch for the `==>` lines):
1. Install Docker.
2. Add swap memory.
3. Write `.env.production` with new random passwords. This file stays on the server and never goes to GitHub.
4. Build the app (5–10 minutes the first time).
5. Set up the database and load the demo company.
6. Start everything.

It ends with:

```
Demo link:      https://13-233-10-20.sslip.io
Sign in as:     riya.requester@demo.orrfin.ai (or arjun.buyer, neha.approver, vikram.finance, anita.admin)
Password:       Demo-1a2b3c4d
```

Open the link. The first visit can take up to a minute while the free HTTPS certificate is issued. The demo
password is new and random: share it only with the people you demo to. It is not the one in the README.

**Check it works:** sign in as Riya → raise a need → sign in as Neha and approve → sign in as Arjun →
**Procure → Orders** (README section "Intake to procure, need first").

## Part H. Optional: switch on the AI

Without a key the demo works, but these features change:
- **Invoice reading:** an uploaded invoice goes to *manual entry* after 3 tries. A person types the fields; matching and approval then work normally.
- **The intake agent and the assistant** say "unavailable".
- **The WhatsApp/email reader** falls back to a simple "number + item" reading.

1. Get a key at **https://aistudio.google.com/apikey**.
2. On the server, open the settings file:
   ```
   cd /opt/orrfin && nano .env.production
   ```
3. Put the key after `GEMINI_API_KEY=`. Save with **Ctrl+O**, Enter, then exit with **Ctrl+X**.
4. Restart the API and worker:
   ```
   docker compose -f infra/docker-compose.prod.yml --env-file .env.production up -d --force-recreate api worker
   ```

## Part I. Optional: use your own domain (demo.orrfin.ai)

1. At your domain registrar's DNS page, add an **A record**:
   - name `demo`;
   - value = the Elastic IP from Part D;
   - TTL 300.
2. Wait about 10 minutes.
3. On the server, `nano /opt/orrfin/.env.production` and change three lines:
   ```
   SITE_ADDRESS=demo.orrfin.ai
   PUBLIC_WEB_URL=https://demo.orrfin.ai
   CORS_ORIGINS=["https://demo.orrfin.ai"]
   ```
4. Run `bash infra/deploy.sh` again.

## Part J. Update the demo after new work

1. On your laptop, commit and push to GitHub as usual.
2. On the server (Part E to open the terminal):
   ```
   sudo -i
   cd /opt/orrfin && bash infra/deploy.sh
   ```

**Tag the version you demo** so you can always return to it:
- On the laptop:
  ```
  git tag demo-20261120-1 && git push origin demo-20261120-1
  ```
- To roll back on the server:
  ```
  bash infra/deploy.sh demo-20261120-1
  ```

## Part K. Backups (5 minutes, once)

**Daily snapshot of the whole disk:**
1. EC2 left menu → **Lifecycle Manager** → **Create lifecycle policy** → **EBS snapshot policy**.
2. Target: *Instance*, tag `Name` = `orrfin-demo`.
3. Schedule: **daily**, keep **7**.
4. **Create policy**.

**Database copy on demand:**
```
cd /opt/orrfin
docker compose -f infra/docker-compose.prod.yml --env-file .env.production exec -T postgres pg_dump -U orrfin orrfin | gzip > /root/orrfin-$(date +%F).sql.gz
```

## Part L. Stop it when not demoing

- **To stop:** EC2 → Instances → tick **orrfin-demo** → **Instance state** → **Stop**. The data stays on the disk.
- **To start:** **Instance state** → **Start**. Wait 2 minutes and the same link works again: the Elastic IP
  keeps the address, and everything restarts by itself.

## If something goes wrong

| What you see | What to do |
|---|---|
| The link doesn't open at all | EC2 → the instance → **Security** tab: inbound must allow 80 and 443. Check the Elastic IP is associated. |
| "Your connection is not private" for a few minutes | Normal on the first visit while the certificate is issued. If it lasts, the server can't be reached on port 80; check the security group. |
| The deploy stops during "Building" | Run `bash infra/deploy.sh` again; it continues. On t3.small it can run out of memory; use t3.medium. |
| The site loads but sign-in fails | Use the password the script printed, not the README one. To see it again: `grep DEMO_PASSWORD /opt/orrfin/.env.production` |
| Anything else | See what the app says: `docker compose -f infra/docker-compose.prod.yml --env-file .env.production logs --tail 100 api` (or `web`, `worker`, `caddy`) |

## How this differs from BUILD_PLAN §10, and what to upgrade before a pilot

For a demo link, everything runs on one server so there is little to set up and little to pay. Before any
real customer data (§12), move these to their own AWS services:

| Demo server (now) | Before a pilot |
|---|---|
| Database in a Docker container, daily disk snapshots | **RDS PostgreSQL** with automated backups and a tested restore. Change only `DATABASE_URL`. |
| Uploaded files on the server's disk | **S3**, private and versioned. Needs a small S3 `FileStore` adapter, which isn't built yet. |
| Secrets in `/opt/orrfin/.env.production` (readable by root only) | **AWS Secrets Manager** |
| Shared demo password | Real accounts, two-step sign-in required for admin and finance |
| No monitoring | CloudWatch alarms, uptime checks, Cloudflare in front (bot protection, rate limits) |
