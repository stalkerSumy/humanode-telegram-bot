# Troubleshooting

## Connection Issues When Using IPv6 Tunnels

If your server uses an IPv6 tunnel (e.g., from services like he.net) for network access, the bot may be unstable or fail to connect to Telegram's servers.

### The Core Issue

The Telegram API prefers connections over IPv6. If your server has IPv6 configured, the bot will attempt to use it by default.

The problem is related to the **MTU (Maximum Transmission Unit)**. The bot operates reliably only with a native connection that has a standard MTU of 1500. Tunnels typically have a smaller MTU, which can cause the connection to drop when exchanging data with Telegram's servers.

### Recommendations

For stable bot operation, it is recommended to use a server with one of the following connection types:
1.  **A native IPv4 connection.**
2.  **A native IPv6 connection with a standard MTU of 1500.**

If you are using a tunnel and encountering errors, the simplest solution is to disable IPv6 on your server. This will ensure all bot traffic is routed through your IPv4 connection.
