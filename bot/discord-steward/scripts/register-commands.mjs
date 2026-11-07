const token = requireEnv("DISCORD_BOT_TOKEN");
const applicationId = requireEnv("DISCORD_APPLICATION_ID");
const guildId = process.env.DISCORD_GUILD_ID;

const commands = [
  {
    name: "bug",
    description: "File a BoulderRoller bug report for staff triage.",
    type: 1,
    contexts: [0],
    integration_types: [0]
  },
  {
    name: "feedback",
    description: "Send a product idea or rider feedback to the BoulderRoller team.",
    type: 1,
    contexts: [0],
    integration_types: [0]
  },
  {
    name: "support",
    description: "Ask BoulderRoller staff for help.",
    type: 1,
    contexts: [0],
    integration_types: [0]
  },
  {
    name: "ride-report",
    description: "Report a route, climb, reward, or ride-data issue.",
    type: 1,
    contexts: [0],
    integration_types: [0]
  }
];

const route = guildId
  ? `/applications/${applicationId}/guilds/${guildId}/commands`
  : `/applications/${applicationId}/commands`;

const response = await fetch(`https://discord.com/api/v10${route}`, {
  method: "PUT",
  headers: {
    Authorization: `Bot ${token}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify(commands)
});

const body = await response.text();
if (!response.ok) {
  throw new Error(`Command registration failed (${response.status}): ${body}`);
}

console.log(body);

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing ${name}`);
  }
  return value;
}
