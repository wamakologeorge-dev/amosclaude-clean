# Amosclaud Applications

Amosclaud Applications are installable developer capabilities that can be shared across Amosclaud organizations without making GitHub the control plane.

An application is not required to be a mobile or desktop app. It is an Amosclaud-native application identity with declared permissions, optional agent and SpaceCodeMe access, organization-scoped installations, credentials, webhooks, settings, and distribution metadata.

## Lifecycle

1. A developer creates an Amosclaud Application and declares the permissions it may request.
2. An organization administrator installs the application into one organization and approves a subset of those permissions.
3. Amosclaud creates a unique installation identity for that organization.
4. Installation credentials are scoped to that installation and can be rotated or revoked without affecting installations in other organizations.
5. Every privileged application action is expected to be attributable to the application and installation identity in the Amosclaud audit trail.

## Core permission families

The first-party scope vocabulary includes repository read/write, workspace read/execute, Amosclaud Agent invocation, Amosclaud SpaceCodeMe access, Actions execution, deployment staging/production, storage access, and webhook management. Secret values are not granted by default and production deployment remains an explicit permission.

## Settings surfaces

The Amosclaud Settings experience groups application management under **Integrations** with Installed Applications, Developer Applications, Application Installations, Amosclaud API, API Keys & Tokens, OAuth Applications, Service Accounts, Agent Connections, Webhooks, and Marketplace.

The Code, planning and automation group uses Amosclaud-native product names including **Amosclaud Agent** and **Amosclaud SpaceCodeMe**.
