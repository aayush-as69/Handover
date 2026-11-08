# CampusEvents: Sprint review

Date: 2026-10-03. Attendees: Meera Iyer, Riya Sharma, Arjun Nair.

## Status
- Event listing is live on the staging site.
- Booking API is merged. Row-level locking is in (PR 2).

## Decisions
- Seat locks will go in Redis. (Riya)

## Risks
- In a test, two users were able to book the same seat. Riya is investigating.

## Open questions
- Refund policy: full, partial or none? Meera will ask the faculty advisor.

## Next actions
- Riya: fix the double-booking problem.
- Meera: get the refund policy answer.
- QR check-in at the venue: someone should look at this.
