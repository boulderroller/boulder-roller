# Move the self-hosted iOS runner to its own macOS user

**Why.** iOS CI (`.github/workflows/ios-ci.yml`) runs every non-draft pull request that touches `ios/` or `workout-parse/`, and every push to `main` that touches `ios/`, on the Mac's self-hosted runner. Until this move, that runner ran as Tim's account. Anything a build executed could read what Tim's account can, including:
- the Solana keys in `~/.config/solana`, among them the upgrade authority;
- `~/.ssh`, which is root on the production server.

Blind-spot item BS-008. Tim chose a separate standard user on 14 Oct 2026.

**What stays the same.** The runner keeps the label `boulder-ios`, so the workflow needs no change. Xcode, the iOS simulator runtimes and Homebrew's `xcodegen` are shared read-only. Tim's key files are already mode 600, so the new user can't read them; step 3 closes the rest of the home folder.

The whole move takes about 15 minutes and needs your admin password.

**Fast path.** `bash scripts/isolate-ios-runner.sh` from your account does steps 1–11. It asks for your admin password and the new user's password. Then tell Claude. The manual steps below are the same work.

**It starts at boot.** The runner is a boot-time service, so iOS CI picks up again after any reboot once you've unlocked the Mac. Nobody logs in to CI Runner. Step 10 has the details and the undo.

## From your account

1. Check that no iOS CI job is running (GitHub → Actions), then stop the old runner: press Ctrl-C in the terminal where it runs, or:

```bash
pkill -TERM -f Runner.Listener
```

2. Create the standard (non-admin) CI user. It prompts for that user's password; keep it in your password manager.

```bash
sudo sysadminctl -addUser ci -fullName "CI Runner" -password -
```

`sysadminctl` exits 0 even when it fails, so confirm the user exists:

```bash
id ci
```

3. Lock your home folder to yourself:

```bash
chmod 700 /Users/gabetemp
```

4. Finish Xcode's first-run setup for every user:

```bash
sudo xcodebuild -runFirstLaunch
```

5. Get a runner registration token. It's valid for an hour; copy it.

```bash
gh api -X POST repos/dungbeetlephoenix/boulder-roller/actions/runners/registration-token --jq .token
```

## As the CI user

Switch to **CI Runner** with fast user switching (Control Center → your name → CI Runner) and open Terminal there. After step 10, CI Runner can log out; the runner doesn't need its session.

6. Install Rust and the two iOS targets the parser build uses:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
```

```bash
~/.cargo/bin/rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

7. Put Homebrew's tools and Cargo on the path, then open a new Terminal tab. The runner records the PATH it is configured with for every job, so set it outright rather than extending one inherited from your account (whose folders `ci` can't read):

```bash
echo 'export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$PATH"' >> ~/.zprofile
```

```bash
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
```

8. Download the runner, at the same version as before:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner && curl -fsSLo runner.tar.gz https://github.com/actions/runner/releases/download/v2.338.0/actions-runner-osx-arm64-2.338.0.tar.gz && tar xzf runner.tar.gz
```

9. Register it with the token from step 5:

```bash
./config.sh --url https://github.com/dungbeetlephoenix/boulder-roller --token PASTE_TOKEN --labels boulder-ios --name boulder-ios-ci --unattended
```

## Back in your account

Switch back to your account.

10. Install the runner as a boot-time service, from your account:

```bash
bash scripts/ios-runner-boot-service.sh
```

It defines two launchd jobs, both in root-owned files. The runner job runs `runsvc.sh` as `ci` in `ci`'s own launchd user domain, where the iOS Simulator works without a login session. A boot daemon only loads that job at startup. Root runs nothing but `/bin/sh` and `launchctl` on root-owned paths: CI jobs run untrusted code as `ci`, so nothing `ci` can write may ever run as root. Don't use the runner's `svc.sh` on this Mac; it installs a login-only agent that would start a second runner.

To restart the runner:

```bash
sudo launchctl kickstart -k user/$(id -u ci)/actions.runner.dungbeetlephoenix-boulder-roller.boulder-ios-ci
```

To go back to the login service, run the script with `--undo`, then log in to CI Runner once.

11. Remove the old runner's registration:

```bash
cd ~/actions-runner && ./config.sh remove --token "$(gh api -X POST repos/dungbeetlephoenix/boulder-roller/actions/runners/remove-token --jq .token)"
```

12. Tell Claude. Claude then confirms that:
- `boulder-ios-ci` is online and runs as `ci`;
- a manual iOS CI run passes on it;
- the `ci` user can't read your home folder.

After that, the old `~/actions-runner` folder in your account can go. On 21 Oct 2026 its registration was confirmed gone and the folder was moved to the Trash (2.5 GB until the Trash is emptied).

**An existing install with an inherited PATH** (jobs log harmless `EACCES` on `/Users/gabetemp/...`): `ios-runner-boot-service.sh` resets the runner's recorded PATH when it installs the service.

## Still separate

CI deploys use your personal SSH key as the `DROPLET_SSH_KEY` secret. The deploy job runs on GitHub's Linux machines, not this runner, but a key used only for deploys would limit what a leaked secret can reach. That's the other half of BS-008.

A manual run can still choose GitHub's paid Mac when this Mac is off.
