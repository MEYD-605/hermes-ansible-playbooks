# hermes-ansible-playbooks

Public Ansible playbooks for [Hermes Agent](https://github.com/NousResearch/hermes-agent) nodes.

Three jobs, three playbooks. Do not mix them.

1. **Job A** — brand-new Linux box → one UNIX user, one systemd gateway
2. **Job B** — existing macOS multi-seat host → config hygiene across `~/.hermes-<seat>/`
3. **Job C** — add one more seat on that Mac → own venv + launchd plist

Extracted from a private fleet lab and published without live inventory, tokens, or host names.

## Quick start

```bash
git clone https://github.com/MEYD-605/hermes-ansible-playbooks.git
cd hermes-ansible-playbooks

python3 -m pip install --user ansible
ansible-galaxy collection install -r requirements.yml

cp inventory/hosts.example.ini inventory/hosts.ini
cp group_vars/all.example.yml group_vars/all.yml
# edit those two files — they are gitignored
```

Ping first, then run one job:

```bash
# Job A — fresh Linux node
ansible -i inventory/hosts.ini hermes_nodes -m ping
ansible-playbook playbooks/deploy-hermes-node.yml

# Job C — new seat on this Mac
ansible-playbook playbooks/deploy-hermes-seat-macos.yml \
  -e seat_name=myseat

# Job B — hygiene across seats listed in group_vars/all.yml
ansible-playbook playbooks/macos-fleet-hygiene.yml
```

## What each playbook does

**`playbooks/deploy-hermes-node.yml`** (Linux)

- create `hermes` user + group
- apt: git, curl, build-essential, ffmpeg, ripgrep, fail2ban
- install `uv`, optional Playwright Chromium deps
- clone `NousResearch/hermes-agent`, `uv venv`, `uv pip install -e ".[all]"`
- systemd unit `hermes-gateway.service`
- optional copy of a local fleet skill tree
- pin `mcp==1.28.1` (mcp 2.x breaks Hermes 0.19.x)
- `hermes doctor`

**`playbooks/deploy-hermes-seat-macos.yml`** (macOS seat)

- refuse to run without `-e seat_name=...`
- refuse a venv that is a symlink to another seat
- dedicated `~/.hermes-<seat>/venv` via `uv`
- LaunchAgent `ai.hermes.gateway-<seat>.plist` (`KeepAlive`, 30s throttle)
- optional TUI build (`npm` must be `<11.10` or `>=12`)
- warn-only tmux / resume-target health checks

**`playbooks/macos-fleet-hygiene.yml`** (macOS fleet)

- `0700` on each seat home, `0600` on existing `.env`
- enforce compression + hard-stop via each seat's **own** venv python
- optional skill sync, Firecrawl probe, local knowledge-API probe
- probes are **off** unless you pass `-e firecrawl_required=true` / `-e arra_required=true`

## Hard rules (learned the expensive way)

- **`--check` is not a test.** `command` / `shell` tasks are skipped in check mode. `apt` + `service` chains also lie. Run for real, then grep the target file.
- **Never write `VAR=val cmd` inside `ansible.builtin.command`.** Use the module `environment:` key. `command` execs argv[0] with no shell.
- **Loop each seat's own `~/.hermes-<seat>/venv/bin/python`.** Do not reuse one seat's interpreter and only swap `HERMES_HOME`.
- **Split `hermes_profiles_all` vs `hermes_profiles_with_venv`.** A directory without a venv will fail every config-set task. Count seats from disk (`ls -d ~/.hermes-*`) before you loop.
- **Do not hard-assert optional services.** Firecrawl / local knowledge APIs are opt-in so a public clone does not fail on a quiet laptop.
- **Secrets stay out of this repo.** Tokens live in each seat's `~/.hermes-<seat>/.env` (mode 0600) or Ansible Vault. `inventory/hosts.ini` and `group_vars/all.yml` are gitignored.

## Layout

```text
playbooks/
  deploy-hermes-node.yml
  deploy-hermes-seat-macos.yml
  macos-fleet-hygiene.yml
inventory/
  hosts.example.ini      # copy → hosts.ini
group_vars/
  all.example.yml        # copy → all.yml
ansible.cfg
requirements.yml
```

## Requirements

- Ansible 2.16+
- Collections: `community.general`, `ansible.posix`
- Job A target: Debian/Ubuntu, Python 3.11–3.13, sudo
- Job B/C controller: macOS, `uv`, a checkout of `NousResearch/hermes-agent`

## License

MIT. See [LICENSE](LICENSE).
