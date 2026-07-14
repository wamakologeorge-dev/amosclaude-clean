# Amosclaud Appliance Mode

Amosclaud Appliance Mode turns a dedicated Linux computer into a single-computer Amosclaud platform while preserving owner control and recovery access.

The first implementation is non-destructive: install Linux normally, download Amosclaud, and run the appliance bootstrap. The bootstrap configures the services and firewall but does not repartition storage, remove the operating system, or disable recovery access.

## Service startup order

1. `amosclaud-core`
   - configuration
   - encrypted Vault
   - service discovery
   - health records
   - recovery state
2. `amosclaud-api-gateway`
   - approved API entry point
   - authentication and permissions
   - request limits and audit records
3. `cloud_cmood_agent`
   - agent jobs
   - repository operations
   - local-model requests through the gateway
4. local model runtime
5. web dashboard

Each service waits for the earlier services to report healthy before starting.

## Security wall

The default network policy is deny-by-default:

- dashboard available only on `127.0.0.1:8000`
- model runtime available only inside the local container network
- Vault, database, and registry never exposed as public ports
- inbound network access disabled unless the owner explicitly enables LAN or public mode
- public mode requires HTTPS and authenticated access

## Recovery requirements

Appliance Mode must always preserve:

- owner login and local console access
- a way to stop the agent independently
- service logs and diagnostics
- encrypted backups
- configuration reset and rollback
- the ability to uninstall Amosclaud without losing control of the computer

The appliance secures Amosclaud services; it must never lock the owner out of their own hardware.
