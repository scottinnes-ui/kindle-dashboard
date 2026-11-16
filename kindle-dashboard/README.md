# Kindle 4 dashboard (Glasgow weather + world clock)

A Kindle 4 (non-touch, firmware 4.1.4) version of the abdenourgnx/re-kindle dashboard, set to Glasgow
with a world clock in place of prayer times. Screens: **Today** and **10 days** (see `preview/`).

## How it works

The repo's own extension targets a Kindle 7th gen (touch, firmware 5.12, FBInk), which a Kindle 4 can't run.
So the work is split:

- **GitHub Actions** (`.github/workflows/render.yml`) runs `server/dashboard.py` every 30 minutes. It gets
  Open-Meteo weather for Glasgow, works out the world clock, draws two 600x800 16-grey PNGs and publishes
  them on **GitHub Pages**. No PC needs to stay on.
- **The Kindle** (`kindle/extensions/dashboard`, a KUAL extension) downloads
  `.../today.png` (or `10d.png`) every 10 minutes, shows it with `eips -g`, and freezes the Kindle UI while
  it runs. Hardware buttons replace the touch tabs.

## 1. GitHub setup (scottinnes-ui)

1. Create a **public** repository named `kindle-dashboard` (Pages is free for public repos).
2. Put the contents of this folder in it, including the hidden `.github` folder. With git:
   ```
   cd kindle-dashboard
   git init -b main
   git add .
   git commit -m "Kindle dashboard"
   git remote add origin https://github.com/scottinnes-ui/kindle-dashboard.git
   git push -u origin main
   ```
3. Repo **Settings > Pages > Build and deployment > Source: GitHub Actions**.
4. **Actions** tab > "Render Kindle dashboard" > **Run workflow**. After about a minute
   `https://scottinnes-ui.github.io/kindle-dashboard/` should show both screens.

If you pick a different repo name, change `URL` in `kindle/extensions/dashboard/settings.conf` to match.

## 2. Kindle setup

1. Copy `kindle\extensions\dashboard` to `D:\extensions\dashboard`.
2. Check `settings.conf` (`URL`). Keep **LF** line endings (VS Code / Notepad++ / current Notepad).
3. Eject, open KUAL > **Dashboard**:
   - **Test HTTPS download**: do this first, see the next section.
   - **Test: show one frame (20 s)**, then **Start dashboard**.

## The HTTPS question (the main risk)

GitHub Pages is HTTPS only, and a Kindle 4's `wget` usually has no HTTPS support and its curl/OpenSSL is
very old. The **Test HTTPS download** item shows OK/FAIL for `wget`, `curl` and `curl -k` on screen.

- `curl` OK: nothing to do (`FETCHER="auto"` falls back to it).
- Only `curl -k` OK: set `CURL_INSECURE=1` in `settings.conf` (skips certificate checks; fine for a public
  weather picture, but it is not verified).
- All FAIL (likely if the TLS version is too old): the Kindle can't talk to GitHub directly. Options:
  a plain-HTTP relay that fetches the Pages URL for the Kindle (a Raspberry Pi/NAS/small server, or a
  Cloudflare Worker if its plain-HTTP URL works for you), or the original PC mode (`server\run_server.bat`,
  set `URL` to `http://<pc-ip>:8080/dashboard.png`).

## Notes on the GitHub setup

- Scheduled runs can be late by 5 to 15 minutes. If a data fetch fails the job fails on purpose
  (`--strict`) so the last good picture stays published.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days; re-enable under the Actions
  tab, or push any commit.
- Battery % can't be shown in this mode (the picture is made on GitHub, not per request).
- Change `PLACE`, `LAT`/`LON`, `TIMEZONE` or the six `WORLD_CITIES` at the top of `server/dashboard.py`
  and push; the next run uses them. Test locally with `python server/dashboard.py --demo --once test.png`.

## Buttons while it runs

- Home / Back: stop and return to the Kindle UI (restarts the framework, about 30 s).
- Page buttons or 5-way left/right: switch Today / 10 days.

Codes are in `settings.conf` (`HOME_KEYS`, `NEXT_KEYS`); **Key test** in the KUAL menu prints the raw codes.
If nothing responds, hold the power switch about 20 s to force a reboot.

## Not tested on a real Kindle 4

The script logic was tested with stubbed Kindle commands, and the PNGs are valid 600x800 8-bit greyscale,
but check these on the device: `eips -g` PNG support, picture orientation (`ROT` 90/180/270 in
`settings.conf` applies to PC mode only; for GitHub mode set the rotation in the workflow's `dashboard.py`
commands with `--rot`), the button event device and codes, and the HTTPS test above. Debug log:
`D:\extensions\dashboard\dashboard.log`.

The Kindle stays awake with Wi-Fi on, so keep it on a USB charger if wall-mounted.
