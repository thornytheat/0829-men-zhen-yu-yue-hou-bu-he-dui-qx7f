from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    audit = single(rows,'audit')
    occupied = {}
    attendees = set()
    for row in by_kind(rows,'initial'):
        slot, person = row['slot'],row['attendee']
        if not slot or not person or slot in occupied or person in attendees or row['minute']:
            raise DomainIssue('SLOT_COLLISION')
        occupied[slot] = person
        attendees.add(person)
    waits = by_kind(rows,'wait')
    identities = {r['attendee'] for r in waits}
    if len(identities) != len(waits) or identities.intersection(attendees) or any(not r['attendee'] or r['expires']<=r['minute'] for r in waits):
        raise DomainIssue('WAITLIST_CONFLICT')
    events = sorted((r for r in rows if r['kind'] in {'wait','cancel'} and r['minute']<=audit['minute']),key=lambda r:(r['minute'],r['kind']=='cancel',r['slot'],r['attendee'],r['record']))
    return prepared(len(occupied)+len(waits),{'slots':len(occupied),'events':len(events),'as_of':audit['minute']},(occupied,events,audit['priority']))
