"""Bounded terminal presentation. No process, queue, network, or service actions."""
from __future__ import annotations

import math
import os
import re
import unicodedata

_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
_COLORS = {'ink': '38;5;252', 'muted': '38;5;244', 'line': '38;5;238',
           'ice': '38;5;117', 'glow': '38;5;223', 'good': '38;5;150',
           'warn': '38;5;215', 'bad': '38;5;210', 'bright': '1;38;5;255', 'violet': '38;5;147'}


def clean(value):
    text = _ANSI.sub('', str(value))
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in text)


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
               for c in _ANSI.sub('', text))


def fit(value, width, *, pad=False):
    text = clean(value)
    width = max(0, width)
    if cells(text) > width:
        result, used = [], 0
        for c in text:
            size = cells(c)
            if used + size > max(0, width - 1):
                break
            result.append(c)
            used += size
        text = ''.join(result) + ('…' if width else '')
    return text + (' ' * max(0, width - cells(text)) if pad else '')


def paint(text, tone='ink'):
    return text if os.environ.get('NO_COLOR') else '\x1b[' + _COLORS[tone] + 'm' + text + '\x1b[0m'


def number(value, default=0):
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return default


def records(state):
    items = state.get('requests', {})
    if not isinstance(items, dict):
        return []
    result = []
    for ident, item in reversed(list(items.items())):
        if not isinstance(item, dict):
            continue
        status = str(item.get('status', 'unknown')).upper()
        status = {'ERROR': 'FAILED', 'PROCESSING': 'RUNNING', 'PENDING': 'QUEUED'}.get(status, status)
        result.append((clean(ident), status))
    return result


def orbit(frame, width=29, height=7, active=False):
    """A slow eclipse orbit; motion is decorative, never a progress percentage."""
    cx, cy = (width - 1) / 2, (height - 1) / 2
    rx, ry = max(1, cx - 2), max(1, cy - .2)
    grid = [[(' ', 'muted') for _ in range(width)] for _ in range(height)]
    for step in range(180):
        a = step * math.tau / 180
        x, y = round(cx + rx * math.cos(a)), round(cy + ry * math.sin(a))
        grid[y][x] = ('·', 'line')
    for y in range(height):
        for x in range(width):
            radius = ((x - cx) / max(1, rx * .43)) ** 2 + ((y - cy) / max(1, ry * .85)) ** 2
            if .58 <= radius <= 1.3:
                grid[y][x] = ('•' if x <= cx else '·', 'glow' if x <= cx else 'muted')
            elif radius < .58:
                grid[y][x] = (' ', 'ink')
    for offset, glyph, tone in [(0, '●', 'ice'), (math.pi, '·', 'glow')]:
        angle = frame * (.10 if active else .045) + offset
        x, y = round(cx + rx * math.cos(angle)), round(cy + ry * math.sin(angle))
        grid[y][x] = (glyph, tone)
    grid[round(cy)][round(cx)] = ('◉', 'bright')
    return [''.join(paint(c, tone) for c, tone in row) for row in grid]


def status_model(state, status):
    """A stopped supervisor must not override a separately verified live watcher."""
    local_count = state.get('watcher_count')
    reported = number(status.get('watcher_count')) if status.get('heartbeat') == 'FRESH' else 0
    live = number(local_count) if local_count is not None else reported
    if not live and local_count is None and state.get('running') is True:
        live = 1
    running = number(state.get('running_tasks'))
    queued = number(state.get('queued'), sum(s == 'QUEUED' for _, s in records(state)))
    confirmed_absent = state.get('process_probe') == 'ABSENT' and local_count == 0
    offline = not live and confirmed_absent and status.get('service') == 'DOWN'
    mood = 'WORKING' if live and running else 'READY' if live else 'OFFLINE' if offline else 'CHECK'
    return live, running, queued, mood


def bridge_scene(frame, width, active=False, height=3):
    """Compact suspension bridge, with separate request and result lanes."""
    width = max(1, width)
    if width < 28:
        return []
    left, right = max(5, width // 4), min(width - 6, width * 3 // 4)
    top = [' '] * width
    for x in (left, right):
        top[x] = '╥'
    for x in range(left + 1, right):
        t = (x - left) / (right - left)
        top[x] = '╲' if t < .2 else '╱' if t > .8 else '─'
    down, up = ['─'] * width, ['─'] * width
    for x in (left, right):
        down[x], up[x] = '╫', '╨'
    for row, label in [(down, 'DOCS → '), (up, 'LOCAL ← ')]:
        row[:len(label)] = label
    span = max(1, width - 16)
    speed = frame // (1 if active else 4)
    down[8 + speed % span] = '◆' if active else '·'
    up[8 + (span - 1 - speed % span)] = '◆' if active else '·'
    result = [paint(''.join(top), 'line'), paint(''.join(down), 'ice'), paint(''.join(up), 'violet')]
    if height >= 5:
        result = [paint(' ' * left + '◈' + ' ' * (right - left - 1) + '◈', 'glow'), *result,
                  paint(fit('REQUEST → queue → local execution → durable result', width, pad=True), 'muted')]
    return result


def _wrap(text, width):
    width = max(1, width)
    out, line, used = [], '', 0
    for c in clean(text):
        size = cells(c)
        if line and used + size > width:
            out.append(line);line, used = '', 0
        line += c;used += size
    return out + [line] if line else out


def panel(title, values, width, height, tone='ice'):
    if height <= 0:
        return []
    if width < 5:
        return [paint(fit(x, width, pad=True), tone) for x in [title, *values][:height]]
    inner = width - 2
    label = fit(' ' + title.upper() + ' ', inner)
    result = [paint('╭' + label + '─' * max(0, inner - cells(label)) + '╮', tone)]
    if height == 1:
        return result
    for i in range(max(0, height - 2)):
        text = values[i] if i < len(values) else ''
        result.append(paint('│', 'line') + paint(fit(' ' + text, inner, pad=True), 'ink') + paint('│', 'line'))
    result.append(paint('╰' + '─' * inner + '╯', 'line'))
    return result


def render(state, status, columns, rows, frame=0, flash_message='', page=0, scroll=0):
    """Dense operations grid; narrow screens retain all data through named views."""
    state = state if isinstance(state, dict) else {}
    status = status if isinstance(status, dict) else {}
    width, height = max(1, number(columns, 80) - 1), max(1, number(rows, 24) - 1)
    frame = 0 if os.environ.get('BRIDGE_UI_REDUCED_MOTION') == '1' else number(frame)
    page = number(page) % 5
    names = ['OVERVIEW', 'HISTORY', 'TASK', 'HEALTH', 'LINKS']
    live, running, queued, mood = status_model(state, status)
    tone = 'ice' if mood == 'WORKING' else 'good' if mood == 'READY' else 'bad' if mood == 'OFFLINE' else 'warn'
    entries = records(state)
    requests = state.get('requests', {})
    active = next((ident for ident, label in entries if label == 'RUNNING'), None) if running else None
    service = clean(status.get('service', 'UNKNOWN'))
    completed, failed, interrupted = number(state.get('completed')), number(state.get('errors')), number(state.get('interrupted'))
    sup = state.get('supervisor_health') or {}
    if not isinstance(sup, dict):sup = {}
    sup_fresh = state.get('supervisor_fresh', status.get('heartbeat') == 'FRESH')
    supervisor = clean(sup.get('mode') or status.get('supervisor') or 'not reported') if sup_fresh else 'STALE / NOT ATTACHED'
    owner = clean(state.get('ownership') or ('existing watcher' if live else 'not verified'))
    heartbeat = str(status.get('heartbeat_age_s', '—')) + 's' if status.get('heartbeat') == 'FRESH' else 'stale / unavailable'
    recoveries = sup.get('restarts', status.get('recoveries', '—'))
    task = state.get('task') or state.get('active_task') or status.get('task') or status.get('active_task') or {}
    if not isinstance(task, dict):task = {'id': task}
    task_id = clean(task.get('id') or task.get('task_id') or task.get('name') or 'Not linked')
    phase, attempt, pending = [clean(task.get(key, 'not exposed')) for key in ('phase', 'attempt', 'pending')]
    providers = state.get('providers') if isinstance(state.get('providers'), dict) else {}
    links = [name + '  ' + ('configured' if providers.get(name) else 'not reported') for name in ('ChatGPT', 'Gemini')]
    source = clean(state.get('queue_source', 'state snapshot'))
    activity = [('RUN ' + active) if active else 'RUNNING · ID not exposed' if running else 'IDLE · waiting for requests' if live else 'Watcher not verified']
    if not live and running:activity = ['RECORDED RUNNING · watcher not verified']
    recent = [label.lower().ljust(11) + ' ' + ident for ident, label in entries]
    metrics = 'RUN ' + str(running) + '  WAIT ' + str(queued) + '  DONE ' + str(completed) + '  FAIL ' + str(failed) + '  INT ' + str(interrupted)
    items = [
        ('WATCHER / SERVICE', ['Watcher ' + str(live) + ' · PID ' + str(state.get('pid', '—')),
                               'Service ' + service + ' · ' + owner, 'Supervisor ' + supervisor], 'ice'),
        ('RECENT EXECUTIONS', recent or ['No requests recorded'], 'violet'),
        ('ECLIPSE TASK', ['Task ' + task_id, 'Phase ' + phase + ' · attempt ' + attempt, 'Pending ' + pending], 'glow'),
        ('RECOVERY / HEALTH', ['Heartbeat ' + heartbeat, 'Recoveries ' + str(recoveries) + ' · interrupted ' + str(interrupted),
                               'Failed ' + str(failed) + ' · queue ' + source], 'warn'),
        ('PROVIDER LINKS', [*links, 'Durable queue + local result receipts'], 'ice'),
        ('CONTROLS', ['BRIDGE menu · service controls', 'BRIDGE status / logs / doctor', 'Q closes view; watcher stays running'], 'violet')]
    out = []
    def row(text='', color='ink'):
        out.append(paint(fit(text, width, pad=True), color))
    if width < 28 or height < 10:
        for text in ['ECLIPSE BRIDGE · ' + mood, names[page], *activity, metrics,
                     'Service ' + service, 'PID ' + str(state.get('pid', '—')), 'Tab views · Q close'][:height]:
            row(text, tone)
        if flash_message and height > 1:out[1] = paint(fit(flash_message, width), 'warn')
        return out
    title = ' ECLIPSE / BRIDGE'
    badge = '● ' + mood + ' '
    shine = (frame // 2) % (len(title) + 10) - 4
    heading = ''.join(paint(c, 'bright' if abs(i - shine) < 2 else 'ice') for i, c in enumerate(title))
    out.append(heading + ' ' * max(0, width - cells(title) - cells(badge)) + paint(badge, tone))
    nav = '  '.join(str(i + 1) + ':' + name.title() for i, name in enumerate(names))
    row(nav if width >= cells(nav) else str(page + 1) + '/5 ' + names[page] + ' · Tab changes view', 'violet')
    if page == 0 and height >= 20:
        out.extend(bridge_scene(frame, width, live and running > 0, 5 if height >= 32 else 3))
    for text in activity:row(text, tone)
    row(metrics, 'bright')
    footer = '1–5 views · Tab next · J/K history · Q close' if width >= 48 else '1–5/Tab views · J/K scroll · Q close'
    reserve = 1 + bool(flash_message)
    room = max(0, height - len(out) - reserve)
    if page == 0:
        cols = 2 if width >= 72 else 1
        slots = min(6, (room // 4) * cols)
        # Stable priorities, never rotate diagnostics out from under the reader.
        selected = items[:slots]
        if selected:
            rows_needed = (len(selected) + cols - 1) // cols
            panel_h = room // rows_needed
            for start in range(0, len(selected), cols):
                group = selected[start:start + cols]
                if cols == 2 and len(group) == 2:
                    left_w = (width - 1) // 2;right_w = width - left_w - 1
                    left = panel(*group[0][:2], left_w, panel_h, group[0][2])
                    right = panel(*group[1][:2], right_w, panel_h, group[1][2])
                    out.extend(a + ' ' + b for a, b in zip(left, right))
                else:out.extend(panel(*group[0][:2], width, panel_h, group[0][2]))
        elif room:
            for text in [items[0][1][0], items[0][1][1], '2 History · 3 Task · 4 Health · 5 Links'][:room]:row(text)
    else:
        details = (recent or ['No requests recorded']) if page == 1 else [
            'Task ID  ' + task_id, 'Phase  ' + phase, 'Attempt  ' + attempt, 'Pending  ' + pending,
            'Bridge request  ' + (active or 'none executing')] if page == 2 else [
            *items[0][1], *items[3][1], 'Ownership  ' + owner,
            'Supervisor record  ' + ('fresh' if sup_fresh else 'stale; not current ownership'),
            'Queue records  ' + str(number(state.get('total')))] if page == 3 else [
            *links, 'ChatGPT document  ' + clean(state.get('doc_id') or 'not reported'),
            'Gemini document  ' + clean(state.get('gemini_doc_id') or 'not reported'),
            'Queue source  ' + source, 'Queued  ' + str(queued),
            'Local execution; durable result recovery', *items[5][1]]
        wrapped = [line for text in details for line in _wrap(text, max(1, width - 4))]
        if page == 1:wrapped = wrapped[number(scroll):]
        out.extend(panel(names[page], wrapped, width, room, 'violet' if page == 1 else 'ice'))
    out = out[:max(0, height - reserve)]
    if flash_message:row(flash_message, 'warn')
    while len(out) < height - 1:row()
    row(footer, 'muted')
    return out[:height]
