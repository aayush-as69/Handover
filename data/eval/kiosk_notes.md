# Library kiosk: planning notes

Date: 2026-10-25. Attendees: Dev Patel, Ana Rossi, Sam Okafor.

## Decisions
- Use the existing campus single sign-on for staff login. Reason: staff already have accounts and nobody has to reset passwords.
- Catalogue search stays on simple SQL LIKE queries until the book count passes 20,000.

## Risks
- The kiosk touch screen firmware is out of warranty and has no spare unit.

## Open questions
- Who approves the late-fee waiver policy? Ana to ask the librarian by 2026-11-02.

## Next actions
- Dev: backup script and nightly schedule by 2026-11-05.
