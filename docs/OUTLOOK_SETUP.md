# Outlook Setup

Outlook integration is not part of Phase 0 or Phase 1.

Future Outlook integration must:

- Use delegated Microsoft identity.
- Request `Mail.ReadWrite` only when draft creation is implemented.
- Never request `Mail.Send`.
- Store tokens outside SQLite using OS credential storage where feasible.
- Create drafts only after explicit user approval.
- Never send messages.
