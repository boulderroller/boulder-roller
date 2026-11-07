# Boulder Rollers MCP Server

MCP (Model Context Protocol) server providing dynamic query tools for Claude Code.

## Tools

### vault-status
Query on-chain vault state by ID or signature hash.
```
vault-status 123
vault-status abc123def...
```

### ride-trace
Trace a ride through the processing pipeline.
```
ride-trace 550e8400-e29b-41d4-a716-446655440000
```

### droplet-health
Check staging droplet status.
```
droplet-health
```

### wallet-state
Query wallet balances, stakes, and BeetleCard.
```
wallet-state 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU
```

## Installation

```bash
cd tools/mcp-server
npm install
npm run build
```

## Configuration

Add to your Claude Code MCP config (`~/.config/claude-code/mcp.json`):

```json
{
  "mcpServers": {
    "boulder-rollers": {
      "command": "node",
      "args": ["/path/to/BoulderRoller-v2/tools/mcp-server/dist/index.js"],
      "env": {
        "DB_HOST": "db.qzkqjevawthyboymqrle.supabase.co",
        "DB_PORT": "5432",
        "DB_USER": "postgres",
        "DB_PASSWORD": "your-password",
        "DB_NAME": "postgres"
      }
    }
  }
}
```

## Development

```bash
npm run dev  # Uses tsx for hot reloading
```
