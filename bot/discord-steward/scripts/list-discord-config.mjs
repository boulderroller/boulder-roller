const token = requireEnv("DISCORD_BOT_TOKEN");
const guildId = requireEnv("DISCORD_GUILD_ID");

const [channels, roles] = await Promise.all([
  discord(`/guilds/${guildId}/channels`),
  discord(`/guilds/${guildId}/roles`)
]);

console.log("# Channels");
for (const channel of channels
  .filter((channel) => channel.type === 0)
  .sort((a, b) => a.position - b.position)) {
  console.log(`${channel.name}=${channel.id}`);
}

console.log("\n# Roles");
for (const role of roles.sort((a, b) => b.position - a.position)) {
  console.log(`${role.name}=${role.id}`);
}

async function discord(path) {
  const response = await fetch(`https://discord.com/api/v10${path}`, {
    headers: { Authorization: `Bot ${token}` }
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`Discord API failed (${response.status}): ${body}`);
  }
  return JSON.parse(body);
}

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing ${name}`);
  }
  return value;
}
