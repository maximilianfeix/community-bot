# Security

## Reporting a vulnerability

Please report it privately through GitHub:
[open a security advisory](https://github.com/maximilianfeix/community-bot/security/advisories/new).
Do not open a public issue and do not post it on the Discord server.

## What the bot can do

- On Discord: view channels, send messages with embeds and files, manage messages, manage channels,
  manage roles and mention roles that members cannot mention, in one configured server. It is not an administrator, reads no message content and uses
  no privileged intent.
- On the network: GET requests to `api.github.com`, and Discord's API. Nothing else.
- On the server: a dedicated system user without a shell, a read-only file system apart from its own state
  directory, no capabilities.

## What is in scope

- Making the bot ping people or roles it should not, or post text from GitHub unsanitised.
- Making the bot hand out a role other than its own notification roles.
- Making the bot change or delete a channel, role or message it did not create.
- Getting a token into a log, an error message or the state file.
- Reaching the deploy secrets from a pull request.
