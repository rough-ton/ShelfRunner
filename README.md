<p align="center">
  <img src="https://github.com/user-attachments/assets/bb80c1db-03cc-470a-a105-723448b73ee1" width="80%" />
</p>

**Prowlarr → Download Client → Kindle**

Search for ebooks via your Prowlarr indexer, push them to your download client, and automatically deliver the file to your Kindle via email — all from a self-hosted web UI.

---

## How It Works

1. You search — ShelfRunner queries Prowlarr's `/api/v1/search` with `type=book`
2. You click **Send to Kindle** — ShelfRunner POSTs to Prowlarr's `/api/v1/download`, which pushes the release to your configured download client (qBittorrent, NZBGet, etc.)
3. A background thread watches your download directory for new ebook files (`.epub`, `.mobi`, `.azw3`, `.pdf`)
4. Once the file lands, ShelfRunner emails it to your Kindle address via SMTP with subject `convert` — which tells Amazon to auto-convert the format if needed
5. The **Queue** button in the UI shows live job status: `downloading → sending → done`

---

## Requirements

- Docker + Docker Compose
- A running Prowlarr instance with at least one book indexer configured
- A download client configured in Prowlarr (qBittorrent, Deluge, NZBGet, SABnzbd, etc.)
- A Gmail account (or any SMTP provider) to send files to Kindle
- Your Kindle personal document email address

---

## Quick Start

### 1. Get the files

```bash
tar -xzf shelfrunner.tar.gz
cd shelfrunner
```

### 2. Configure

```bash
cp .env.example .env
$EDITOR .env
```

### 3. Allow your sender address in Amazon

Amazon only delivers files from approved addresses. This step is **required** or all deliveries will silently fail.

1. Go to amazon.com/myk (Manage Your Kindle)
2. Navigate to **Preferences → Personal Document Settings**
3. Under **Approved Personal Document E-mail List**, add the address you set as `SMTP_FROM`

### 4. Run

```bash
docker-compose up -d
```

Open `http://your-server:5000` in a browser.

---

## Configuration Reference

### Prowlarr

| Variable | Description | Example |
|---|---|---|
| `PROWLARR_URL` | Full URL to your Prowlarr instance | `http://192.168.1.10:9696` |
| `PROWLARR_APIKEY` | Found in Prowlarr → Settings → General | `abc123def456` |

If Prowlarr is on the same Docker host, use its container name as the hostname (e.g. `http://prowlarr:9696`) provided both containers share a Docker network.

### Download Directory

| Variable | Description | Example |
|---|---|---|
| `HOST_DOWNLOAD_DIR` | Path on your **host machine** where your download client writes completed files | `/mnt/media/downloads` |
| `DOWNLOAD_DIR` | Path **inside the container** — leave as `/downloads` | `/downloads` |

ShelfRunner mounts `HOST_DOWNLOAD_DIR` read-only into the container at `/downloads` and watches it recursively for new ebook files.

### Kindle Delivery

| Variable | Description | Example |
|---|---|---|
| `KINDLE_EMAIL` | Your Kindle personal document address | `yourname_abc@kindle.com` |
| `SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port (587 = STARTTLS) | `587` |
| `SMTP_USER` | SMTP login username | `you@gmail.com` |
| `SMTP_PASS` | SMTP password or app password | `abcd efgh ijkl mnop` |
| `SMTP_FROM` | From address on the email | `you@gmail.com` |

### Gmail App Password

Google requires an App Password for SMTP — your regular password will not work.

1. Enable 2-Step Verification on your Google account
2. Go to myaccount.google.com/apppasswords
3. Create a new app password (name it "ShelfRunner")
4. Use the generated 16-character password as `SMTP_PASS`

### Tuning

| Variable | Default | Description |
|---|---|---|
| `POLL_TIMEOUT` | `300` | Seconds to wait for a download before marking the job timed out |
| `POLL_INTERVAL` | `10` | Seconds between checks of the download directory |

---

## Project Structure

```
shelfrunner/
├── app/
│   ├── main.py          # Flask app, API routes, background watcher, SMTP delivery
│   └── routes.py        # Serves the frontend
├── templates/
│   └── index.html       # Full UI — search, results, job queue, status panel
├── server.py            # Gunicorn entrypoint
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Server config status (no secrets exposed) |
| `GET` | `/api/search?q=<query>` | Search Prowlarr for ebooks |
| `POST` | `/api/send` | Push release to download client, queue Kindle delivery |
| `GET` | `/api/jobs` | List all delivery jobs |
| `GET` | `/api/jobs/<id>` | Get a single job status |

### Job Status Values

| Status | Meaning |
|---|---|
| `downloading` | Waiting for file to appear in download directory |
| `sending` | File found, SMTP delivery in progress |
| `done` | File successfully emailed to Kindle |
| `timeout` | File did not appear within `POLL_TIMEOUT` seconds |
| `error` | SMTP delivery failed — check `docker-compose logs` |

---

## Troubleshooting

**Jobs stuck at `downloading`**
- Verify `HOST_DOWNLOAD_DIR` is the correct host path and the download client is writing there
- Run `docker-compose config` to confirm the resolved volume mount path
- Increase `POLL_TIMEOUT` for slow connections

**Jobs going to `error`**
- Check logs: `docker-compose logs -f shelfrunner`
- Most common cause: wrong SMTP credentials, or `SMTP_FROM` not in Amazon's approved senders list

**Nothing in search results**
- Confirm Prowlarr has at least one book-capable indexer enabled and tested
- Test directly: `curl "http://prowlarr:9696/api/v1/search?query=test&type=book&apikey=YOUR_KEY"`

**Kindle not receiving files**
- Confirm `SMTP_FROM` is in your Amazon approved senders list (amazon.com/myk)
- Amazon has a 50MB limit for personal document delivery

## Updating

```bash
docker-compose down
docker-compose up -d --build
```
