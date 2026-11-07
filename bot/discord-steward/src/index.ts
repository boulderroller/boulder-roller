import nacl from "tweetnacl";

const DISCORD_API = "https://discord.com/api/v10";
const EPHEMERAL = 1 << 6;

const InteractionType = {
  Ping: 1,
  ApplicationCommand: 2,
  MessageComponent: 3,
  ModalSubmit: 5
} as const;

const ResponseType = {
  Pong: 1,
  ChannelMessageWithSource: 4,
  UpdateMessage: 7,
  Modal: 9
} as const;

const ComponentType = {
  ActionRow: 1,
  Button: 2,
  TextInput: 4
} as const;

const ButtonStyle = {
  Primary: 1,
  Secondary: 2,
  Success: 3,
  Danger: 4
} as const;

const TextInputStyle = {
  Short: 1,
  Paragraph: 2
} as const;

type IntakeType = "bug" | "feedback" | "support" | "ride_report";
type IntakeStatus = "new" | "acknowledged" | "needs_details" | "bd_ready" | "closed";
type StaffAction = "ack" | "needs_details" | "bd_ready" | "close";

interface DiscordUser {
  id: string;
  username?: string;
  global_name?: string | null;
}

interface DiscordMember {
  user?: DiscordUser;
  roles?: string[];
  permissions?: string;
}

interface DiscordInteraction {
  id: string;
  application_id: string;
  type: number;
  token: string;
  guild_id?: string;
  channel_id?: string;
  member?: DiscordMember;
  user?: DiscordUser;
  data?: {
    name?: string;
    custom_id?: string;
    components?: ModalActionRow[];
  };
}

interface ModalActionRow {
  components?: Array<{
    custom_id?: string;
    value?: string;
  }>;
}

interface Actor {
  id: string;
  tag: string;
}

interface IntakeRecord {
  id: string;
  type: IntakeType;
  status: IntakeStatus;
  title: string;
  reporterId: string;
  reporterTag: string;
  guildId: string | null;
  sourceChannelId: string | null;
  targetChannelId: string | null;
  staffMessageId: string | null;
  fields: Record<string, string>;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
}

interface IntakeRow {
  id: string;
  type: IntakeType;
  status: IntakeStatus;
  title: string;
  reporter_id: string;
  reporter_tag: string;
  guild_id: string | null;
  source_channel_id: string | null;
  target_channel_id: string | null;
  staff_message_id: string | null;
  fields_json: string;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

interface DiscordMessagePayload {
  content?: string;
  embeds?: DiscordEmbed[];
  components?: DiscordActionRow[];
  allowed_mentions?: {
    parse: string[];
  };
}

interface DiscordEmbed {
  title: string;
  description?: string;
  color: number;
  fields: Array<{
    name: string;
    value: string;
    inline?: boolean;
  }>;
  footer?: {
    text: string;
  };
  timestamp?: string;
}

interface DiscordActionRow {
  type: typeof ComponentType.ActionRow;
  components: DiscordButton[];
}

interface DiscordButton {
  type: typeof ComponentType.Button;
  custom_id: string;
  label: string;
  style: number;
  disabled?: boolean;
}

interface DiscordCreateMessageResponse {
  id?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "GET") {
      return jsonResponse({
        service: "br-discord-steward",
        ok: true,
        environment: env.ENVIRONMENT
      });
    }

    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    const body = await request.text();
    const verified = verifyDiscordRequest(request, body, env.DISCORD_PUBLIC_KEY);
    if (!verified) {
      return jsonResponse({ error: "Invalid request signature" }, 401);
    }

    let interaction: DiscordInteraction;
    try {
      interaction = JSON.parse(body) as DiscordInteraction;
    } catch {
      return jsonResponse({ error: "Invalid JSON" }, 400);
    }

    try {
      return await handleInteraction(interaction, env);
    } catch (error) {
      console.error(JSON.stringify({
        event: "interaction_error",
        message: error instanceof Error ? error.message : String(error)
      }));
      return interactionResponse({
        type: ResponseType.ChannelMessageWithSource,
        data: ephemeralMessage("Something went wrong while filing this. Staff can still help in #support.")
      });
    }
  }
} satisfies ExportedHandler<Env>;

async function handleInteraction(interaction: DiscordInteraction, env: Env): Promise<Response> {
  if (interaction.type === InteractionType.Ping) {
    return interactionResponse({ type: ResponseType.Pong });
  }

  if (interaction.type === InteractionType.ApplicationCommand) {
    return handleCommand(interaction);
  }

  if (interaction.type === InteractionType.ModalSubmit) {
    return await handleModalSubmit(interaction, env);
  }

  if (interaction.type === InteractionType.MessageComponent) {
    return await handleStaffAction(interaction, env);
  }

  return interactionResponse({
    type: ResponseType.ChannelMessageWithSource,
    data: ephemeralMessage("I do not know how to handle that interaction yet.")
  });
}

function handleCommand(interaction: DiscordInteraction): Response {
  const commandName = interaction.data?.name;
  if (commandName === "bug") {
    return modalResponse("bug", "File a BoulderRoller Bug", [
      textField("title", "Short title", TextInputStyle.Short, true, "Climb card did not update"),
      textField("surface", "App / device / surface", TextInputStyle.Short, true, "iOS TestFlight, portal, Android, etc."),
      textField("happened", "What happened?", TextInputStyle.Paragraph, true),
      textField("expected", "What did you expect?", TextInputStyle.Paragraph, true),
      textField("link", "Ride, route, screenshot, or URL", TextInputStyle.Short, false)
    ]);
  }

  if (commandName === "feedback") {
    return modalResponse("feedback", "Send BoulderRoller Feedback", [
      textField("title", "Idea or feedback title", TextInputStyle.Short, true),
      textField("rider_context", "Rider context", TextInputStyle.Short, false, "Dogfood rider, builder, first-time user, etc."),
      textField("why", "Why does this matter?", TextInputStyle.Paragraph, true),
      textField("urgency", "Urgency", TextInputStyle.Short, false, "Nice-to-have, annoying, blocking, etc."),
      textField("notes", "Extra notes", TextInputStyle.Paragraph, false)
    ]);
  }

  if (commandName === "support") {
    return modalResponse("support", "Ask BoulderRoller Staff", [
      textField("title", "Support topic", TextInputStyle.Short, true),
      textField("account_context", "Account / wallet / Discord context", TextInputStyle.Short, false),
      textField("device", "Device or browser", TextInputStyle.Short, false),
      textField("dm_ok", "Can staff DM you?", TextInputStyle.Short, true, "Yes / no"),
      textField("details", "What do you need help with?", TextInputStyle.Paragraph, true)
    ]);
  }

  if (commandName === "ride-report") {
    return modalResponse("ride_report", "File a Ride Report", [
      textField("title", "Route, climb, or ride title", TextInputStyle.Short, true),
      textField("date", "Ride date", TextInputStyle.Short, false, "YYYY-MM-DD or rough date"),
      textField("issue_type", "Issue type", TextInputStyle.Short, true, "route data, climb detection, rewards, app UX, other"),
      textField("link", "Ride, route, segment, or screenshot URL", TextInputStyle.Short, false),
      textField("notes", "Notes", TextInputStyle.Paragraph, true)
    ]);
  }

  return interactionResponse({
    type: ResponseType.ChannelMessageWithSource,
    data: ephemeralMessage("Unknown command.")
  });
}

async function handleModalSubmit(interaction: DiscordInteraction, env: Env): Promise<Response> {
  const customId = interaction.data?.custom_id ?? "";
  if (!customId.startsWith("modal:")) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("Unknown intake form.")
    });
  }

  const intakeType = parseIntakeType(customId.slice("modal:".length));
  if (!intakeType) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("Unknown intake type.")
    });
  }

  const fields = extractModalFields(interaction.data?.components ?? []);
  const actor = getActor(interaction);
  const title = firstNonEmpty(fields.title, defaultTitle(intakeType));
  const targetChannelId = targetChannelFor(intakeType, env);
  if (!targetChannelId) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("This bot is missing its staff intake channel configuration.")
    });
  }

  const record = await createIntake(env, {
    type: intakeType,
    title,
    actor,
    fields,
    guildId: interaction.guild_id ?? null,
    sourceChannelId: interaction.channel_id ?? null,
    targetChannelId
  });

  const staffMessageId = await sendDiscordMessage(
    env,
    targetChannelId,
    renderStaffCard(record)
  );

  if (staffMessageId) {
    await setStaffMessageId(env, record.id, staffMessageId);
  }

  return interactionResponse({
    type: ResponseType.ChannelMessageWithSource,
    data: ephemeralMessage(`Filed ${record.id}. Staff can see it in <#${targetChannelId}>.`)
  });
}

async function handleStaffAction(interaction: DiscordInteraction, env: Env): Promise<Response> {
  const customId = interaction.data?.custom_id ?? "";
  const match = /^intake:([^:]+):([^:]+)$/.exec(customId);
  if (!match) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("Unknown button.")
    });
  }

  const action = parseStaffAction(match[1]);
  const intakeId = match[2];
  if (!action || !intakeId) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("Unknown intake action.")
    });
  }

  if (!isStaff(interaction, env.STAFF_ROLE_IDS)) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage("Only BoulderRoller staff can use that action.")
    });
  }

  const actor = getActor(interaction);
  const status = statusForAction(action);
  const updated = await updateIntakeStatus(env, intakeId, status, actor, action);
  if (!updated) {
    return interactionResponse({
      type: ResponseType.ChannelMessageWithSource,
      data: ephemeralMessage(`Could not find ${intakeId}.`)
    });
  }

  return interactionResponse({
    type: ResponseType.UpdateMessage,
    data: renderStaffCard(updated)
  });
}

async function createIntake(
  env: Env,
  input: {
    type: IntakeType;
    title: string;
    actor: Actor;
    fields: Record<string, string>;
    guildId: string | null;
    sourceChannelId: string | null;
    targetChannelId: string;
  }
): Promise<IntakeRecord> {
  const now = new Date().toISOString();
  const year = now.slice(0, 4);
  const sequence = await nextCounter(env, year);
  const id = `BRD-${year}-${String(sequence).padStart(4, "0")}`;

  await env.DB.prepare(
    `INSERT INTO intakes (
      id, type, status, title, reporter_id, reporter_tag, guild_id,
      source_channel_id, target_channel_id, fields_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  )
    .bind(
      id,
      input.type,
      "new",
      truncate(input.title, 180),
      input.actor.id,
      input.actor.tag,
      input.guildId,
      input.sourceChannelId,
      input.targetChannelId,
      JSON.stringify(input.fields),
      now,
      now
    )
    .run();

  await addEvent(env, id, input.actor, "created", null, now);

  return {
    id,
    type: input.type,
    status: "new",
    title: truncate(input.title, 180),
    reporterId: input.actor.id,
    reporterTag: input.actor.tag,
    guildId: input.guildId,
    sourceChannelId: input.sourceChannelId,
    targetChannelId: input.targetChannelId,
    staffMessageId: null,
    fields: input.fields,
    createdAt: now,
    updatedAt: now,
    closedAt: null
  };
}

async function nextCounter(env: Env, scope: string): Promise<number> {
  await env.DB.prepare("INSERT INTO counters (scope, value) VALUES (?, 0) ON CONFLICT(scope) DO NOTHING")
    .bind(scope)
    .run();

  const row = await env.DB.prepare("UPDATE counters SET value = value + 1 WHERE scope = ? RETURNING value")
    .bind(scope)
    .first<{ value: number }>();

  if (!row) {
    throw new Error("Failed to allocate intake id");
  }

  return row.value;
}

async function setStaffMessageId(env: Env, intakeId: string, messageId: string): Promise<void> {
  await env.DB.prepare("UPDATE intakes SET staff_message_id = ?, updated_at = ? WHERE id = ?")
    .bind(messageId, new Date().toISOString(), intakeId)
    .run();
}

async function updateIntakeStatus(
  env: Env,
  intakeId: string,
  status: IntakeStatus,
  actor: Actor,
  action: StaffAction
): Promise<IntakeRecord | null> {
  const existing = await getIntake(env, intakeId);
  if (!existing) {
    return null;
  }

  const now = new Date().toISOString();
  const closedAt = status === "closed" ? now : null;
  await env.DB.prepare("UPDATE intakes SET status = ?, updated_at = ?, closed_at = ? WHERE id = ?")
    .bind(status, now, closedAt, intakeId)
    .run();
  await addEvent(env, intakeId, actor, action, null, now);
  return await getIntake(env, intakeId);
}

async function getIntake(env: Env, intakeId: string): Promise<IntakeRecord | null> {
  const row = await env.DB.prepare("SELECT * FROM intakes WHERE id = ?")
    .bind(intakeId)
    .first<IntakeRow>();
  return row ? rowToIntake(row) : null;
}

async function addEvent(
  env: Env,
  intakeId: string,
  actor: Actor,
  action: string,
  note: string | null,
  createdAt: string
): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO intake_events (intake_id, actor_id, actor_tag, action, note, created_at) VALUES (?, ?, ?, ?, ?, ?)"
  )
    .bind(intakeId, actor.id, actor.tag, action, note, createdAt)
    .run();
}

function rowToIntake(row: IntakeRow): IntakeRecord {
  return {
    id: row.id,
    type: row.type,
    status: row.status,
    title: row.title,
    reporterId: row.reporter_id,
    reporterTag: row.reporter_tag,
    guildId: row.guild_id,
    sourceChannelId: row.source_channel_id,
    targetChannelId: row.target_channel_id,
    staffMessageId: row.staff_message_id,
    fields: parseFields(row.fields_json),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    closedAt: row.closed_at
  };
}

async function sendDiscordMessage(
  env: Env,
  channelId: string,
  payload: DiscordMessagePayload
): Promise<string | null> {
  const token = getRuntimeSecret(env, "DISCORD_BOT_TOKEN");
  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is not configured");
  }

  const response = await fetch(`${DISCORD_API}/channels/${channelId}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bot ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  const body = await response.text();
  if (!response.ok) {
    throw new Error(`Discord create message failed (${response.status}): ${body}`);
  }

  const data = JSON.parse(body) as DiscordCreateMessageResponse;
  return data.id ?? null;
}

function renderStaffCard(record: IntakeRecord): DiscordMessagePayload {
  const fields = fieldEntries(record.fields)
    .slice(0, 8)
    .map(([key, value]) => ({
      name: labelForField(key),
      value: truncate(value, 900),
      inline: false
    }));

  fields.unshift({
    name: "Reporter",
    value: `<@${record.reporterId}> (${escapeMarkdown(record.reporterTag)})`,
    inline: false
  });

  if (record.sourceChannelId) {
    fields.push({
      name: "Source",
      value: `<#${record.sourceChannelId}>`,
      inline: true
    });
  }

  if (record.status === "bd_ready") {
    fields.push({
      name: "bd command",
      value: codeBlock(bdCommand(record)),
      inline: false
    });
  }

  const closed = record.status === "closed";
  return {
    embeds: [
      {
        title: `${record.id} - ${typeLabel(record.type)} - ${statusLabel(record.status)}`,
        description: truncate(record.title, 240),
        color: colorForStatus(record.status),
        fields,
        footer: { text: "BoulderRoller Steward" },
        timestamp: record.updatedAt
      }
    ],
    components: [
      {
        type: ComponentType.ActionRow,
        components: [
          button(record.id, "ack", "Acknowledge", ButtonStyle.Primary, closed || record.status === "acknowledged"),
          button(record.id, "needs_details", "Needs Details", ButtonStyle.Secondary, closed),
          button(record.id, "bd_ready", "Convert to bd", ButtonStyle.Success, closed || record.status === "bd_ready"),
          button(record.id, "close", "Close", ButtonStyle.Danger, closed)
        ]
      }
    ],
    allowed_mentions: { parse: [] }
  };
}

function button(
  intakeId: string,
  action: StaffAction,
  label: string,
  style: number,
  disabled: boolean
): DiscordButton {
  return {
    type: ComponentType.Button,
    custom_id: `intake:${action}:${intakeId}`,
    label,
    style,
    disabled
  };
}

function modalResponse(type: IntakeType, title: string, fields: TextFieldDefinition[]): Response {
  return interactionResponse({
    type: ResponseType.Modal,
    data: {
      custom_id: `modal:${type}`,
      title,
      components: fields.map((field) => ({
        type: ComponentType.ActionRow,
        components: [
          {
            type: ComponentType.TextInput,
            custom_id: field.id,
            label: field.label,
            style: field.style,
            required: field.required,
            max_length: field.maxLength,
            placeholder: field.placeholder
          }
        ]
      }))
    }
  });
}

interface TextFieldDefinition {
  id: string;
  label: string;
  style: number;
  required: boolean;
  maxLength: number;
  placeholder?: string;
}

function textField(
  id: string,
  label: string,
  style: number,
  required: boolean,
  placeholder?: string
): TextFieldDefinition {
  const base = {
    id,
    label,
    style,
    required,
    maxLength: style === TextInputStyle.Paragraph ? 1600 : 180
  };
  return placeholder ? { ...base, placeholder } : base;
}

function interactionResponse(payload: unknown, status = 200): Response {
  return jsonResponse(payload, status);
}

function ephemeralMessage(content: string): DiscordMessagePayload & { flags: number } {
  return {
    content,
    flags: EPHEMERAL,
    allowed_mentions: { parse: [] }
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8"
    }
  });
}

function verifyDiscordRequest(request: Request, body: string, publicKeyHex: string): boolean {
  if (!publicKeyHex) {
    console.error(JSON.stringify({ event: "missing_public_key" }));
    return false;
  }

  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp = request.headers.get("X-Signature-Timestamp");
  if (!signature || !timestamp) {
    return false;
  }

  try {
    const message = new TextEncoder().encode(`${timestamp}${body}`);
    return nacl.sign.detached.verify(
      message,
      hexToBytes(signature),
      hexToBytes(publicKeyHex)
    );
  } catch {
    return false;
  }
}

function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new Error("Invalid hex string length");
  }

  const bytes = new Uint8Array(hex.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    const parsed = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
    if (Number.isNaN(parsed)) {
      throw new Error("Invalid hex string");
    }
    bytes[index] = parsed;
  }
  return bytes;
}

function extractModalFields(rows: ModalActionRow[]): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const row of rows) {
    for (const component of row.components ?? []) {
      if (component.custom_id) {
        fields[component.custom_id] = (component.value ?? "").trim();
      }
    }
  }
  return fields;
}

function parseFields(json: string): Record<string, string> {
  const parsed = JSON.parse(json) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {};
  }

  const fields: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === "string" && value.trim()) {
      fields[key] = value.trim();
    }
  }
  return fields;
}

function fieldEntries(fields: Record<string, string>): Array<[string, string]> {
  return Object.entries(fields).filter(([, value]) => value.trim().length > 0);
}

function parseIntakeType(type: string): IntakeType | null {
  if (type === "bug" || type === "feedback" || type === "support" || type === "ride_report") {
    return type;
  }
  return null;
}

function parseStaffAction(action: string | undefined): StaffAction | null {
  if (action === "ack" || action === "needs_details" || action === "bd_ready" || action === "close") {
    return action;
  }
  return null;
}

function statusForAction(action: StaffAction): IntakeStatus {
  if (action === "ack") return "acknowledged";
  if (action === "needs_details") return "needs_details";
  if (action === "bd_ready") return "bd_ready";
  return "closed";
}

function targetChannelFor(type: IntakeType, env: Env): string {
  if (type === "bug") return env.BD_INTAKE_CHANNEL_ID || env.STAFF_TRIAGE_CHANNEL_ID;
  if (type === "ride_report") return env.RIDE_INTAKE_CHANNEL_ID || env.BD_INTAKE_CHANNEL_ID || env.STAFF_TRIAGE_CHANNEL_ID;
  if (type === "feedback") return env.FEEDBACK_INTAKE_CHANNEL_ID || env.STAFF_TRIAGE_CHANNEL_ID;
  return env.SUPPORT_INTAKE_CHANNEL_ID || env.STAFF_TRIAGE_CHANNEL_ID;
}

function getActor(interaction: DiscordInteraction): Actor {
  const user = interaction.member?.user ?? interaction.user;
  if (!user) {
    return { id: "unknown", tag: "unknown" };
  }

  return {
    id: user.id,
    tag: user.global_name || user.username || user.id
  };
}

function isStaff(interaction: DiscordInteraction, staffRoleIdsCsv: string): boolean {
  const member = interaction.member;
  if (!member) {
    return false;
  }

  const permissions = BigInt(member.permissions ?? "0");
  const administrator = 1n << 3n;
  const manageGuild = 1n << 5n;
  const manageMessages = 1n << 13n;
  const moderateMembers = 1n << 40n;
  if ((permissions & (administrator | manageGuild | manageMessages | moderateMembers)) !== 0n) {
    return true;
  }

  const staffRoleIds = staffRoleIdsCsv
    .split(",")
    .map((role) => role.trim())
    .filter(Boolean);
  if (staffRoleIds.length === 0) {
    return false;
  }

  const roles = new Set(member.roles ?? []);
  return staffRoleIds.some((roleId) => roles.has(roleId));
}

function getRuntimeSecret(env: Env, key: string): string | null {
  const value = Reflect.get(env, key) as unknown;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function defaultTitle(type: IntakeType): string {
  if (type === "bug") return "Untitled bug";
  if (type === "feedback") return "Untitled feedback";
  if (type === "support") return "Support request";
  return "Ride report";
}

function firstNonEmpty(value: string | undefined, fallback: string): string {
  return value && value.trim() ? value.trim() : fallback;
}

function typeLabel(type: IntakeType): string {
  if (type === "bug") return "Bug";
  if (type === "feedback") return "Feedback";
  if (type === "support") return "Support";
  return "Ride Report";
}

function statusLabel(status: IntakeStatus): string {
  if (status === "new") return "New";
  if (status === "acknowledged") return "Acknowledged";
  if (status === "needs_details") return "Needs Details";
  if (status === "bd_ready") return "bd Ready";
  return "Closed";
}

function colorForStatus(status: IntakeStatus): number {
  if (status === "new") return 0xf1c40f;
  if (status === "acknowledged") return 0x3498db;
  if (status === "needs_details") return 0xe67e22;
  if (status === "bd_ready") return 0x2ecc71;
  return 0x95a5a6;
}

function labelForField(key: string): string {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function bdCommand(record: IntakeRecord): string {
  const issueType = record.type === "bug" ? "bug" : record.type === "feedback" ? "feature" : "task";
  const description = fieldEntries(record.fields)
    .map(([key, value]) => `${labelForField(key)}: ${value}`)
    .join("\n\n");
  const descriptionBody = truncate(description, 520);
  return [
    "bd create",
    shellQuote(record.title),
    "-t",
    issueType,
    "-p",
    record.type === "bug" ? "1" : "2",
    "--description",
    shellQuote(`${descriptionBody}\n\nDiscord intake: ${record.id}\nReporter: ${record.reporterTag} (${record.reporterId})`),
    "--json"
  ].join(" ");
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, "'\\''")}'`;
}

function codeBlock(value: string): string {
  return `\`\`\`bash\n${truncate(value, 920)}\n\`\`\``;
}

function escapeMarkdown(value: string): string {
  return value.replace(/([\\*_`~|])/g, "\\$1");
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}
