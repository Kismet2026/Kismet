import json
import os
from datetime import datetime

# BaZi (八字) compatibility service
# Computes Chinese astrology compatibility based on birth date/time.
# Uses local calculation (no external API dependency for MVP).

# Heavenly Stems (天干)
STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
STEM_ELEMENTS = ['木', '木', '火', '火', '土', '土', '金', '金', '水', '水']
STEM_NAMES_EN = ['Wood', 'Wood', 'Fire', 'Fire', 'Earth', 'Earth', 'Metal', 'Metal', 'Water', 'Water']

# Earthly Branches (地支)
BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
BRANCH_ELEMENTS = ['水', '土', '木', '木', '土', '火', '火', '土', '金', '金', '土', '水']

# Five elements (五行)
ELEMENTS = {'金': 'metal', '木': 'wood', '水': 'water', '火': 'fire', '土': 'earth'}

# Element compatibility scores (generating: +15, controlling: -10, same: +5)
GENERATE = [('木', '火'), ('火', '土'), ('土', '金'), ('金', '水'), ('水', '木')]
CONTROL = [('木', '土'), ('土', '水'), ('水', '火'), ('火', '金'), ('金', '木')]


def handler(event, context):
    method = _get_method(event)
    path = _get_path(event)

    if method == 'POST' and path == '/bazi/compatibility':
        return calculate_compatibility(event)
    elif method == 'GET' and path.startswith('/bazi/profile/'):
        user_id = path.split('/bazi/profile/')[1]
        return get_bazi_profile(event, user_id)
    else:
        return _response(404, {'code': 'NOT_FOUND', 'message': f'No route: {method} {path}'})


def calculate_compatibility(event):
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    body = _parse_body(event)
    if not body:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': 'Request body required'})

    required = ['userABirthDate', 'userABirthTime', 'userBBirthDate', 'userBBirthTime']
    for field in required:
        if field not in body:
            return _response(400, {'code': 'VALIDATION_ERROR', 'message': f'Missing field: {field}'})

    try:
        chart_a = _compute_bazi_chart(body['userABirthDate'], body['userABirthTime'])
        chart_b = _compute_bazi_chart(body['userBBirthDate'], body['userBBirthTime'])
    except ValueError as e:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': str(e)})

    elements_a = _count_elements(chart_a)
    elements_b = _count_elements(chart_b)

    score = _compute_compatibility_score(chart_a, chart_b)
    analysis = _generate_analysis(score, chart_a, chart_b)

    return _response(200, {
        'compatibilityScore': score,
        'analysis': analysis,
        'userAElements': {
            'year': chart_a['year']['element'],
            'month': chart_a['month']['element'],
            'day': chart_a['day']['element'],
            'hour': chart_a['hour']['element'],
        },
        'userBElements': {
            'year': chart_b['year']['element'],
            'month': chart_b['month']['element'],
            'day': chart_b['day']['element'],
            'hour': chart_b['hour']['element'],
        },
    })


def get_bazi_profile(event, user_id):
    caller_id = _get_user_id(event)
    if not caller_id:
        return _response(401, {'code': 'UNAUTHORIZED', 'message': 'Not authenticated'})

    # In production, fetch birth data from Profile Service.
    # For MVP, accept birth data as query params.
    params = event.get('queryStringParameters') or {}
    birth_date = params.get('birthDate')
    birth_time = params.get('birthTime', '12:00')

    if not birth_date:
        return _response(404, {'code': 'NOT_FOUND', 'message': 'Birth data not available. Provide birthDate query param.'})

    try:
        chart = _compute_bazi_chart(birth_date, birth_time)
    except ValueError as e:
        return _response(400, {'code': 'VALIDATION_ERROR', 'message': str(e)})

    elements = _count_elements(chart)
    summary = _generate_profile_summary(chart, elements)

    return _response(200, {
        'userId': user_id,
        'birthDate': birth_date,
        'birthTime': birth_time,
        'baziChart': {
            'yearPillar': {'heavenlyStem': chart['year']['stem'], 'earthlyBranch': chart['year']['branch'], 'element': chart['year']['element']},
            'monthPillar': {'heavenlyStem': chart['month']['stem'], 'earthlyBranch': chart['month']['branch'], 'element': chart['month']['element']},
            'dayPillar': {'heavenlyStem': chart['day']['stem'], 'earthlyBranch': chart['day']['branch'], 'element': chart['day']['element']},
            'hourPillar': {'heavenlyStem': chart['hour']['stem'], 'earthlyBranch': chart['hour']['branch'], 'element': chart['hour']['element']},
        },
        'fiveElements': elements,
        'summary': summary,
    })


# --- BaZi Calculation ---

def _compute_bazi_chart(birth_date_str, birth_time_str):
    """Compute the Four Pillars (四柱) from birth date and time."""
    try:
        birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError(f'Invalid date format: {birth_date_str}. Use YYYY-MM-DD.')

    try:
        parts = birth_time_str.split(':')
        hour = int(parts[0])
    except (ValueError, IndexError):
        raise ValueError(f'Invalid time format: {birth_time_str}. Use HH:mm.')

    year = birth_date.year
    month = birth_date.month
    day = birth_date.day

    # Year pillar
    year_stem_idx = (year - 4) % 10
    year_branch_idx = (year - 4) % 12

    # Month pillar (simplified: based on month number)
    month_stem_idx = (year_stem_idx * 2 + month) % 10
    month_branch_idx = (month + 1) % 12

    # Day pillar (simplified: based on day count from reference)
    ref_date = datetime(1900, 1, 1)
    day_offset = (birth_date - ref_date).days
    day_stem_idx = (day_offset + 9) % 10  # Jan 1 1900 was 甲子
    day_branch_idx = (day_offset + 1) % 12

    # Hour pillar
    hour_branch_idx = ((hour + 1) // 2) % 12
    hour_stem_idx = (day_stem_idx * 2 + hour_branch_idx) % 10

    return {
        'year': {'stem': STEMS[year_stem_idx], 'branch': BRANCHES[year_branch_idx], 'element': STEM_ELEMENTS[year_stem_idx]},
        'month': {'stem': STEMS[month_stem_idx], 'branch': BRANCHES[month_branch_idx], 'element': STEM_ELEMENTS[month_stem_idx]},
        'day': {'stem': STEMS[day_stem_idx], 'branch': BRANCHES[day_branch_idx], 'element': STEM_ELEMENTS[day_stem_idx]},
        'hour': {'stem': STEMS[hour_stem_idx], 'branch': BRANCHES[hour_branch_idx], 'element': STEM_ELEMENTS[hour_stem_idx]},
    }


def _count_elements(chart):
    """Count five elements in a chart."""
    counts = {'metal': 0, 'wood': 0, 'water': 0, 'fire': 0, 'earth': 0}
    for pillar in chart.values():
        stem_idx = STEMS.index(pillar['stem'])
        branch_idx = BRANCHES.index(pillar['branch'])
        stem_element = STEM_ELEMENTS[stem_idx]
        branch_element = BRANCH_ELEMENTS[branch_idx]
        counts[ELEMENTS[stem_element]] += 1
        counts[ELEMENTS[branch_element]] += 1
    return counts


def _compute_compatibility_score(chart_a, chart_b):
    """Compute compatibility score (0-100) between two charts."""
    score = 50  # base score

    for pillar in ['year', 'month', 'day', 'hour']:
        elem_a = chart_a[pillar]['element']
        elem_b = chart_b[pillar]['element']

        if elem_a == elem_b:
            score += 5
        elif (elem_a, elem_b) in GENERATE or (elem_b, elem_a) in GENERATE:
            score += 8
        elif (elem_a, elem_b) in CONTROL or (elem_b, elem_a) in CONTROL:
            score -= 5

    # Day pillar (日柱) has extra weight in marriage compatibility
    day_a = chart_a['day']['element']
    day_b = chart_b['day']['element']
    if (day_a, day_b) in GENERATE or (day_b, day_a) in GENERATE:
        score += 10
    elif day_a == day_b:
        score += 5

    return max(0, min(100, score))


def _generate_analysis(score, chart_a, chart_b):
    """Generate a Chinese analysis string."""
    day_a = chart_a['day']['element']
    day_b = chart_b['day']['element']

    if score >= 85:
        prefix = '天作之合'
    elif score >= 70:
        prefix = '良缘佳配'
    elif score >= 55:
        prefix = '中等缘分'
    else:
        prefix = '需多磨合'

    pair = f'{day_a}{day_b}'
    if (day_a, day_b) in GENERATE or (day_b, day_a) in GENERATE:
        detail = f'五行相生，{day_a}{day_b}互补，感情运势佳。'
    elif day_a == day_b:
        detail = f'日柱同属{day_a}，性格相近，易有共鸣。'
    elif (day_a, day_b) in CONTROL or (day_b, day_a) in CONTROL:
        detail = f'{day_a}{day_b}相克，需互相包容理解。'
    else:
        detail = '五行关系平和，可顺其自然发展。'

    return f'{prefix}，{detail}'


def _generate_profile_summary(chart, elements):
    """Generate a summary of the BaZi profile."""
    day_stem = chart['day']['stem']
    day_element = chart['day']['element']

    max_element = max(elements, key=elements.get)
    min_element = min(elements, key=elements.get)

    element_cn = {'metal': '金', 'wood': '木', 'water': '水', 'fire': '火', 'earth': '土'}
    return f'日主{day_stem}{day_element}，{element_cn[max_element]}旺{element_cn[min_element]}弱。'


# --- Helpers ---

def _get_method(event):
    return (
        event.get('requestContext', {}).get('http', {}).get('method')
        or event.get('httpMethod')
        or ''
    ).upper()


def _get_path(event):
    path = (
        event.get('rawPath')
        or event.get('path')
        or event.get('requestContext', {}).get('http', {}).get('path')
        or '/'
    )
    return path.rstrip('/') if path != '/' else path


def _get_user_id(event):
    claims = (
        event.get('requestContext', {}).get('authorizer', {}).get('claims')
        or event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims')
        or {}
    )
    return claims.get('sub') or claims.get('cognito:username')


def _parse_body(event):
    body = event.get('body')
    if not body:
        return None
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body, ensure_ascii=False),
    }
