# FreeToken-Bots (safe MVP)

Pi-oriented OpenRouter free-model discovery for Muse, Grokbot and Dot child-agent workflows.

> ⚠️ **安装要求：这个 skill 自己不会扫描。** 必须配一个每天早上 8 点（本地时间）跑 `scripts/radar.py scan` 的定时任务（cron / launchd / systemd timer 三选一），否则免费模型名单会过期。装完第一件事就是把这个定时任务建起来。

## Commands

```bash
python3 scripts/radar.py scan
python3 scripts/radar.py status
OPENROUTER_API_KEY='your-key' python3 scripts/radar.py probe --model 'exact-model-id'
python3 scripts/radar.py sync --dry-run
```

Uses Python standard library only. `sync` does **not** mutate Pi yet: Pi schema detection, trusted parameter verification, separate tool-call probing and transactional config updates are planned follow-ups. Never install this expecting full unattended failover. The skill documents safe host-side integration steps.

## Safety fixes (0.1.3)

- Every probe fetches the current model catalog before resolving the model ID. If the fetch fails or the catalog is malformed, no completion is sent; cached prices never authorize probes.
- Cache reads reject malformed reports, invalid model ID lists, timezone-naive timestamps, future timestamps, and reports older than 24 hours.
- Probe success exits with code 0; refused or failed probes exit with code 1; argument errors use code 2.
- Prices can still change between validation and execution. This is not a server-enforced zero-spend guarantee.

Run the offline regression tests:

```bash
python3 -B -m unittest discover -s tests -v
```

Source: [limin112/min-skill — FreeToken-Bots](https://github.com/limin112/min-skill/tree/2f3075f4037cb90f28720b87d7e381f168ee690e/skills/FreeToken-Bots), with the safety fixes above.
