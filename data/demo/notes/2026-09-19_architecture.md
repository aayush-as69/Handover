# CampusEvents: Architecture meeting

Date: 2026-09-19. Attendees: Meera Iyer, Riya Sharma, Arjun Nair. Guest: Mr. Rao (alumnus mentor).

## Decisions
- PostgreSQL is the only datastore. Reason: seat booking needs transactions, and we do not
  want to run a second database. No other datastore will be added without a meeting.
- Payment gateway is PayNest. Reason: it has a free sandbox and the sponsor already has an
  account. Its v1 API shuts down on 2026-12-31. We start on v1 because the v2 sandbox is not
  open yet, then migrate to v2 before that date.
- Riya owns all payments work.

## Dependencies
- PayNest sandbox access depends on the sponsor approving our application. Meera is
  following up.
- The checkout page (Arjun) depends on the backend payment endpoints (Riya).

## Contacts
- Mr. Rao knows the campus IT office and can help with campus SSO later.

## Risks
- Gateway sandbox approval could be delayed.
