from app.business import decision


def policy(result):
    return decision(result,'STALE_CANCELLATION' if result['flag'] else None)
