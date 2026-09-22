"""Evidence checkpoints for research completion; no API calls or fabricated facts."""
from datetime import datetime


def followers_errors(item):
    metrics = item.get('metrics')
    record = metrics.get('followers') if isinstance(metrics, dict) else None
    if not isinstance(record, dict):
        return ['metrics.followers.not_queried']
    errors = []
    expected = {'youtube': 'subscribers', 'x': 'followers', 'twitch': 'followers'}.get(
        item.get('creator', {}).get('platform'))
    if not expected or record.get('metric') != expected:
        errors.append('metrics.followers.metric')
    if not isinstance(record.get('source'), str) or not record['source'].strip():
        errors.append('metrics.followers.source')
    try:
        timestamp = datetime.fromisoformat(record['checked_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Timezone required')
    except (KeyError, TypeError, AttributeError, ValueError):
        errors.append('metrics.followers.checked_at')
    value, status = record.get('value'), record.get('status')
    if status == 'found':
        if type(value) is not int or value < 0:
            errors.append('metrics.followers.value')
    elif status == 'unavailable':
        if value is not None or not isinstance(record.get('reason'), str) or not record['reason'].strip():
            errors.append('metrics.followers.unavailable_reason')
    else:
        errors.append('metrics.followers.unfinished')
    return errors
