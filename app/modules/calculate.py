from app.business import measured


def compute(data):
    from heapq import heappop,heappush
    occupied,events,expected = data
    occupied = dict(occupied)
    waiting, promoted, invalid, expired = [], {}, [], []
    for row in events:
        person, minute = row['attendee'],row['minute']
        if row['kind']=='wait':
            heappush(waiting,(-row['priority'],minute,person,row['expires']))
            continue
        slot = row['slot']
        if occupied.get(slot) != person:
            invalid.append(row['record'])
            continue
        del occupied[slot]
        while waiting:
            _,_,candidate,expires = heappop(waiting)
            if expires <= minute:
                expired.append(candidate)
                continue
            occupied[slot]=candidate
            promoted[slot]=candidate
            break
    return measured(len(occupied),expected,'号',{'occupied':{str(k):v for k,v in occupied.items()},'promoted':{str(k):v for k,v in promoted.items()},'expired':sorted(expired),'invalid_cancels':invalid},bool(invalid))
