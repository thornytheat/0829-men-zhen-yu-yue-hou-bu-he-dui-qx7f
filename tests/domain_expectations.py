EXPECTED = {'0001': (4, 1, 'READY'),
 '0002': (3, 1, 'READY'),
 '0003': (0, None, 'SLOT_COLLISION'),
 '0004': (1, 1, 'STALE_CANCELLATION')}
EVIDENCE = {'0001': {'occupied': {'1': 4},
          'promoted': {'1': 4},
          'expired': [3],
          'invalid_cancels': []},
 '0002': {'occupied': {'1': 7},
          'promoted': {'1': 7},
          'expired': [],
          'invalid_cancels': []}}
