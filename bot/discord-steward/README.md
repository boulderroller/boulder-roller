# BoulderRoller Discord Steward

Discord-native intake bot for the BoulderRoller community server. This is a
Cloudflare Worker that handles Discord HTTP interactions: slash commands,
modals, and staff action buttons. It intentionally does not use an LLM in v1.

## What it does

- `/bug` opens a structured bug-report modal.
- `/feedback` opens a product/rider-feedback modal.
- `/support` opens a staff-help modal.
- `/ride-report` opens a route, climb, reward, or ride-data report modal.
- Each submitted form gets a stable ID like `BRD-2026-0001`.
- Staff cards are posted to the configured staff intake channel.
- Staff buttons update the intake card:
  - `Acknowledge`
  - `Needs Details`
  - `Convert to bd`
  - `Close`
- D1 stores intake records, status, and status history.

## Runtime

- Cloudflare Workers
- Cloudflare D1
- Discord outgoing webhooks for interactions
- Discord REST API for staff-card posts

The Worker only needs the bot token for posting staff cards. It does not need
message-content intent or passive channel monitoring.

## Local setup

```bash
cd bot/discord-steward
npm install
npm run cf:types
npm run typecheck
```

For local development, create `.dev.vars` from `.dev.vars.example` and provide a
Discord bot token.

## Cloudflare setup

The Worker is deployed as `br-discord-steward` and is configured for the
custom domain `discord-steward.boulderroller.xyz`.

Create the D1 database:

```bash
npx wrangler d1 create boulderroller-discord-steward
```

Copy the returned `database_id` into `wrangler.jsonc`, then run:

```bash
npx wrangler d1 migrations apply boulderroller-discord-steward --remote
npx wrangler secret put DISCORD_BOT_TOKEN
npx wrangler deploy
```

`DISCORD_BOT_TOKEN` should be set as a Worker secret, not a checked-in var.

## Discord app setup

In the Discord Developer Portal:

1. Create the application and bot.
2. Copy Application ID, Public Key, and the bot token.
3. Set the Worker vars in `wrangler.jsonc`:
   - `DISCORD_APPLICATION_ID`
   - `DISCORD_PUBLIC_KEY`
   - `DISCORD_GUILD_ID`
   - `STAFF_TRIAGE_CHANNEL_ID`
   - `BD_INTAKE_CHANNEL_ID`
   - `STAFF_ROLE_IDS`
4. Deploy the Worker.
5. Set the application's Interactions Endpoint URL to `https://discord-steward.boulderroller.xyz`.
6. Install the bot into the server with `bot` and `applications.commands` scopes.

Recommended bot permissions:

- View Channels
- Send Messages
- Embed Links
- Read Message History

After the bot is installed, list channel and role IDs:

```bash
DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... npm run discord:config
```

Register guild commands:

```bash
DISCORD_BOT_TOKEN=... \
DISCORD_APPLICATION_ID=... \
DISCORD_GUILD_ID=1507382542247133357 \
npm run commands:register
```

Guild command registration is used for fast iteration. Global registration can
be used later by omitting `DISCORD_GUILD_ID`.

## Channel routing

The Worker routes intake cards with these vars:

- Bugs: `BD_INTAKE_CHANNEL_ID`, falling back to `STAFF_TRIAGE_CHANNEL_ID`
- Ride reports: `RIDE_INTAKE_CHANNEL_ID`, then `BD_INTAKE_CHANNEL_ID`, then `STAFF_TRIAGE_CHANNEL_ID`
- Feedback: `FEEDBACK_INTAKE_CHANNEL_ID`, falling back to `STAFF_TRIAGE_CHANNEL_ID`
- Support: `SUPPORT_INTAKE_CHANNEL_ID`, falling back to `STAFF_TRIAGE_CHANNEL_ID`

For the current server, the intended v1 routing is:

- Bug and ride-report cards -> `#bd-intake`
- Feedback and support cards -> `#staff-triage`

## Staff actions

Staff buttons are allowed for members with one of the configured
`STAFF_ROLE_IDS`, or members with administrator, manage-server, manage-messages,
or moderate-members permissions.

`Convert to bd` does not mutate the repository from Discord. It marks the card
as `bd Ready` and renders a copy-ready `bd create ...` command. This keeps repo
write access inside the normal development workflow.
