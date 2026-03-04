# War Timeline Auto Update

## What it does
- Pulls latest conflict-related headlines from multi-source RSS feeds.
- Builds a timeline with required fields:
  - 时间（北京时间，精确到分钟）
  - 行动方
  - 动作
  - 地点
  - 结果
  - 可信度（A/B/C）
- Updates local web page: `index.html`
- Pushes summary to Feishu every 12 hours.

## Files
- `update_timeline.py` generator
- `run_update.sh` runtime wrapper
- `com.guoxl.war.timeline.plist` launchd schedule (12h)
- Output:
  - `TIMELINE.md`
  - `index.html`
  - `data/timeline.json`

## Run once
```bash
cd /Users/guoxl/.openclaw/war_timeline
python3 update_timeline.py --push
```

## Install 12h scheduler
```bash
cd /Users/guoxl/.openclaw/war_timeline
./install_launchd.sh
```

## Open web page
```bash
open /Users/guoxl/.openclaw/war_timeline/index.html
```

## Publish To GitHub Pages

1. Create GitHub repo `war-timeline-live`.
2. Push this folder to that repo.
3. In GitHub repo settings:
   - Pages -> Source: **GitHub Actions**.
4. Workflow file:
   - `.github/workflows/update-and-deploy.yml`
   - Auto updates every 12 hours and publishes `index.html`.

Published URL format:
- `https://<github-username>.github.io/war-timeline-live/`
