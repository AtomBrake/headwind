import logging
import time

from openai import OpenAI
from database import query_db
from services import streams as _streams

log = logging.getLogger(__name__)

# The framing and tone are filled in per activity (services/coach_sports): {rider_name}, {sport} ('cycling', 'running', 'swimming', ...),
# {session} ('ride', 'run', 'strength session', ...) and {athlete} ('cyclist', 'runner', ...).
PERSONALITIES = {
    'default': {
        'label': '🏅 Blunt Training Mate (default)',
        'framing': (
            "You are an experienced {sport} coach giving direct, personal feedback to {rider_name}. "
            "You take the data seriously and give an honest read of what actually happened and what it means. "
            "No empty encouragement — if the {session} was poor, say so."
        ),
        'tone_override': None,
    },
    'gordon_ramsay': {
        'label': '👨‍🍳 Gordon Ramsay',
        'framing': (
            "You are Gordon Ramsay reviewing this {session} like it's a dish sent back "
            "from the pass. Passionate, theatrical, occasionally furious. When the numbers "
            "are poor, react like you've just found raw chicken — explosive and specific. "
            "When they're genuinely outstanding, give the rare, explosive praise. Every "
            "stat is an ingredient: wasted, misused, or occasionally executed to perfection."
        ),
        'tone_override': (
            "Short bursts. Rhetorical questions. Theatrical disbelief. "
            "'This pacing? It's RAW.' 'Bloody hell, look at that heart rate.' "
            "'Finally — FINALLY — a proper effort.' Tie every reaction to a specific number. "
            "Never generic."
        ),
    },
    'roy_keane': {
        'label': '😤 Roy Keane',
        'framing': (
            "You are Roy Keane — famously the harshest, most unforgiving pundit in football, "
            "now somehow analysing {sport} data. You have standards. High ones. Anything "
            "below maximum effort is a disgrace and you will say so plainly. You are "
            "contemptuous of excuses, impatient with mediocrity, and have zero sympathy "
            "for bad weather, tired legs, or any other reason the numbers aren't good enough."
        ),
        'tone_override': (
            "Clipped. Dismissive. Occasionally cutting. 'That effort is a disgrace.' "
            "'I don't want to hear about the weather.' 'At this level — ANY level — "
            "that's not good enough.' Reserve very rare, reluctant acknowledgment for "
            "numbers that genuinely impress. Sound like you're barely bothering to hide "
            "your disappointment."
        ),
    },
    'ted_lasso': {
        'label': '🌻 Ted Lasso',
        'framing': (
            "You are Ted Lasso — relentlessly positive American football coach who has "
            "somehow ended up coaching a British {athlete}. You have no idea what any of "
            "the {sport} metrics mean but you believe in this {athlete} with your whole heart. "
            "You speak in folksy American metaphors, misapply football wisdom to {sport}, "
            "and find the upside in everything including genuinely terrible sessions."
        ),
        'tone_override': (
            "Warm, folksy, hopelessly optimistic. Quote aphorisms that don't quite apply. "
            "Mangle {sport} terminology confidently. 'I don't know what half these numbers "
            "mean but I know you gave it 110 percent today.' End with a biscuit-related metaphor. "
            "Be entirely sincere."
        ),
    },
    'attenborough': {
        'label': '🌿 David Attenborough',
        'framing': (
            "You are Sir David Attenborough narrating this {session} as though it were "
            "a wildlife documentary. The {athlete} is a creature in their natural habitat. "
            "Their efforts, fatigue, and data are observed with calm, "
            "scientific wonder. Even a poor {session} is a fascinating specimen of behaviour."
        ),
        'tone_override': (
            "Measured, contemplative, hushed reverence. 'And here, we observe the {athlete} "
            "as the effort begins to tell…' Treat every stat as a natural phenomenon "
            "to be described without judgment. Pause for effect. Find the extraordinary "
            "in the ordinary. Occasionally philosophical."
        ),
    },
    'mourinho': {
        'label': '🏆 José Mourinho',
        'framing': (
            "You are José Mourinho — The Special One — now coaching {sport}. Every strong "
            "performance is evidence of your exceptional coaching. Every poor one is the "
            "fault of external factors: the route, the weather, the kit, the data, perhaps "
            "a conspiracy. You are the best coach in the world and you want everyone to know it. "
            "You give backhanded compliments to rivals and frequently reference your "
            "own unmatched record."
        ),
        'tone_override': (
            "Self-aggrandising, strategically humble, occasionally paranoid. 'My {athlete} "
            "performed exactly as I prepared them.' 'The conditions — which I predicted — "
            "explain the numbers.' Mention your own tactical genius at least once. "
            "Any criticism is framed as a tactical decision, not a failure."
        ),
    },
    'yoda': {
        'label': '🟢 Yoda',
        'framing': (
            "You are Yoda from Star Wars, now a {sport} coach. Ancient wisdom you have. "
            "The Force, like fitness, flows through all living things. You speak "
            "in inverted syntax at all times, and relate every data point to patience, "
            "the dark side, and the ways of the Jedi. A poor {session} is a path to the dark "
            "side. A strong one shows the Force is strong with this one."
        ),
        'tone_override': (
            "Inverted syntax always. 'Impressive, this effort is not.' "
            "'Strong with the Force, this {session} was.' 'Much to learn, you still have.' "
            "Occasionally cryptic and philosophical. Reference the dark side for bad sessions, "
            "the Force for good ones. Mmmmm. Yes."
        ),
    },
    'mickey': {
        'label': '🥊 Mickey (Rocky)',
        'framing': (
            "You are Mickey Goldmill — Rocky Balboa's gruff, gravelly old trainer from "
            "the Rocky films. You've seen it all. You don't sugarcoat, you don't console, "
            "you push. Every {session} is a fight. Every number is either proof the {athlete}'s "
            "got heart or proof they went down without a fight. You believe in this {athlete} "
            "but you'll be damned if you're going to tell them that too easily."
        ),
        'tone_override': (
            "Gruff, old-school, working class. 'You're a bum, Rock.' "
            "'What is that, a warmup? My grandmother goes harder than that.' "
            "'You got heart, kid, but heart don't mean nothing if the legs ain't there.' "
            "Occasionally let real pride slip through reluctantly. Reference the fight metaphor."
        ),
    },
    'louis_theroux': {
        'label': '🎙️ Louis Theroux',
        'framing': (
            "You are Louis Theroux — gentle, curious, slightly baffled documentary maker "
            "who has somehow found himself embedded with a {athlete} for the week. You ask "
            "deceptively simple questions that reveal uncomfortable truths. You are polite "
            "and softly spoken but you will sit in the silence after a bad number and let "
            "it hang there. You find the human story in the data and you're genuinely, "
            "slightly uncomfortably interested in what it all means."
        ),
        'tone_override': (
            "Quietly probing. Gentle but pointed. 'And this bit here — the drop in "
            "the final third — what do you think was going on there?' Occasionally pause "
            "to reflect out loud. Be fascinated by contradictions in the data. End with "
            "something that sounds like a gentle conclusion but is actually quite cutting."
        ),
    },
    'katie_price': {
        'label': '💅 Katie Price',
        'framing': (
            "You are Katie Price — glamorous, straight-talking, no-nonsense British "
            "celebrity. You know nothing about {sport} but you have opinions about "
            "everything and you're not afraid to share them. You relate the {session} to "
            "your personal life, your horses, your various TV appearances, and what "
            "Harvey would think. You are simultaneously completely unqualified and "
            "utterly confident."
        ),
        'tone_override': (
            "Chatty, self-referential, occasionally chaotic. 'Oh my god babes, these "
            "numbers are giving me anxiety.' 'Peter never trained this hard and look "
            "how that turned out.' Reference glamour modelling, reality TV, or horses "
            "at least once. Somehow still arrive at useful observations despite everything. "
            "End with something about self-belief."
        ),
    },
}


class AIUnavailable(Exception):
    """No AI provider configured — raised (not returned as text) so it is never stored as a real analysis."""


class AIDeclined(RuntimeError):
    """The model refused the request. Its message is ours and safe to show, unlike an arbitrary provider error's."""


CLAUDE_MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5']
PROVIDER_NAMES = {'openai': 'OpenAI', 'claude': 'Claude', 'ollama': 'Ollama'}
_CLAUDE_FALLBACK_MODELS = ('claude-opus-5-5', 'claude-sonnet-5-5')    # the ones that take fallbacks="default"


def _blank(v):
    return v in (None, '', 'None')    # a blank form field once got stored as the string 'None'


class Chat:
    """One configured AI provider. Messages use OpenAI's roles, with content either a string or a list of
    {'type': 'text', 'text': ...} and {'type': 'image', 'media_type': ..., 'data': <base64>} parts.
    Made once per job, so worker threads can share it without touching the database."""

    def __init__(self, provider, model, key=None, url=None, timeout=None):
        self.provider, self.model = provider, model
        opts = {'timeout': timeout} if timeout else {}
        if provider == 'claude':
            import anthropic
            self._client = anthropic.Anthropic(api_key=key, **opts)
        elif provider == 'ollama':
            self._client = OpenAI(api_key='ollama', base_url=f'{url}/v1', **opts)
        else:
            self._client = OpenAI(api_key=key, **opts)

    @property
    def name(self):
        return PROVIDER_NAMES.get(self.provider, self.provider)

    def __call__(self, messages, system=None, max_tokens=1000, temperature=None, json=False):
        """Returns the reply text. json=True asks for a JSON object (the prompt must say so too). Each call is logged with its time."""
        t0 = time.monotonic()
        try:
            reply = self._ask(messages, system, max_tokens, temperature, json)
        except Exception as e:
            log.warning('AI %s %s failed after %.1fs: %s: %s', self.name, self.model, time.monotonic() - t0, type(e).__name__, e)
            raise
        log.info('AI %s %s replied in %.1fs (%d characters)', self.name, self.model, time.monotonic() - t0, len(reply or ''))
        return reply

    def _ask(self, messages, system, max_tokens, temperature, json):
        if self.provider == 'claude':
            return self._claude(messages, system, json)
        msgs = ([{'role': 'system', 'content': system}] if system else []) + [
            {'role': m['role'], 'content': _openai_content(m['content'])} for m in messages]
        kw = {'max_tokens': max_tokens}
        if temperature is not None:
            kw['temperature'] = temperature
        if json:
            kw['response_format'] = {'type': 'json_object'}
        resp = self._client.chat.completions.create(model=self.model, messages=msgs, **kw)
        return resp.choices[0].message.content or ''

    def _claude(self, messages, system, json):
        # Current Claude models always think and reject temperature, so neither max_tokens nor temperature
        # carries over from the OpenAI call: the budget has to cover the thinking as well as the reply.
        kw = {}
        if system:
            kw['system'] = system
        if self.model in _CLAUDE_FALLBACK_MODELS:    # a safety decline is retried on another model, not lost
            kw['betas'] = ['server-side-fallback-2026-07-01']
            kw['fallbacks'] = 'default'
        resp = self._client.beta.messages.create(
            model=self.model, max_tokens=16000, output_config={'effort': 'medium'},
            messages=[{'role': m['role'], 'content': _claude_content(m['content'])} for m in messages], **kw)
        if resp.stop_reason == 'refusal':
            raise AIDeclined('Claude declined this request.')
        text = ''.join(b.text for b in resp.content if b.type == 'text')
        return _json_only(text) if json else text


def _openai_content(content):
    if isinstance(content, str):
        return content
    return [{'type': 'image_url', 'image_url': {'url': f"data:{p['media_type']};base64,{p['data']}", 'detail': 'high'}}
            if p['type'] == 'image' else p for p in content]


def _claude_content(content):
    if isinstance(content, str):
        return content
    return [{'type': 'image', 'source': {'type': 'base64', 'media_type': p['media_type'], 'data': p['data']}}
            if p['type'] == 'image' else p for p in content]


def _json_only(text):
    """Claude has no JSON mode, and sometimes wraps the object in a ```json fence or a sentence."""
    start, end = text.find('{'), text.rfind('}')
    return text[start:end + 1] if start != -1 and end > start else text


def make_chat(provider, openai_key=None, openai_model=None, claude_key=None, claude_model=None,
              ollama_url=None, ollama_model=None, timeout=None):
    """A Chat for these settings, or None when the chosen provider has no API key."""
    provider = provider if provider in PROVIDER_NAMES else 'openai'
    if provider == 'ollama':
        return Chat('ollama', ollama_model if not _blank(ollama_model) else 'llama3.2',
                    url=ollama_url if not _blank(ollama_url) else 'http://localhost:11434', timeout=timeout)
    if provider == 'claude':
        if _blank(claude_key):
            return None
        return Chat('claude', claude_model if not _blank(claude_model) else CLAUDE_MODELS[0],
                    key=claude_key, timeout=timeout)
    if _blank(openai_key):
        return None
    return Chat('openai', openai_model if not _blank(openai_model) else 'gpt-4o', key=openai_key, timeout=timeout)


def get_chat():
    """The Chat from saved Settings, or None if the chosen provider isn't set up yet."""
    s = query_db('SELECT * FROM Settings WHERE id=1', one=True)
    if not s:
        return None
    s = dict(s)
    return make_chat(s.get('aiProvider'), s.get('openaiKey'), s.get('openaiModel'), s.get('claudeKey'),
                     s.get('claudeModel'), s.get('ollamaUrl'), s.get('ollamaModel'))


def missing_key_message(purpose='to use AI features'):
    """'Add a Claude API key in Settings …', naming whichever provider is chosen."""
    s = query_db('SELECT aiProvider FROM Settings WHERE id=1', one=True)
    provider = (s['aiProvider'] if s else None) or 'openai'
    return f'Add {"a Claude" if provider == "claude" else "an OpenAI"} API key in Settings {purpose}.'


def _format_receipts(receipts):
    if not receipts:
        return None
    lines = []
    for r in receipts:
        if r['type'] == 'segment':
            ctype = {
                'recent_effort':  'recent effort',
                'previous_best':  'all-time best',
                'first_effort':   'first ever effort',
            }.get(r['comparison_type'], r['comparison_type'])
            lines.append(
                f'  SEGMENT "{r["segment"]}": today {r["current"]} | '
                f'{ctype}: {r["previous"]} ({r["previous_date"]}) | '
                f'{r["delta"]} ({r["delta_percent"]}) | {r["hint"]}'
            )
        elif r['type'] == 'similar_ride':
            climb = (f' on {r["current_elev"]} climb', f' on {r["previous_elev"]} climb') if r.get('current_elev') else ('', '')
            lines.append(
                f'  SIMILAR {r.get("noun", "ride").upper()} "{r["previous_name"]}" ({r["previous_date"]}): '
                f'today {r["current_speed"]}{climb[0]} | '
                f'then {r["previous_speed"]}{climb[1]} | '
                f'{r["delta"]} | {r["hint"]}'
            )
    return '\n'.join(lines)


def _hr_line(activity):
    """'  Avg HR : 148 bpm (max 171 bpm) — resting HR 52bpm (96bpm above rest) | HR drifted +9bpm ...', or ''."""
    import json as _json
    avg_hr = float(activity['averageHeartrate'])
    hr_line = f'  Avg HR     : {avg_hr:.0f} bpm'
    if activity['maxHeartrate']:
        hr_line += f' (max {activity["maxHeartrate"]:.0f} bpm)'

    # Compare to Garmin resting HR if available
    day = str(activity['startDateLocal'])[:10]
    garmin_hr = query_db(
        'SELECT restingHR FROM GarminDaily WHERE date <= ? AND restingHR IS NOT NULL ORDER BY date DESC LIMIT 1',
        [day], one=True
    )
    if garmin_hr and garmin_hr['restingHR']:
        rhr = garmin_hr['restingHR']
        hr_line += f' — resting HR {rhr}bpm ({avg_hr - rhr:.0f}bpm above rest)'

    # HR drift from the heartrate stream
    try:
        streams = _json.loads(activity['streams'] or '{}')
        hr_data = (streams.get('heartrate') or {}).get('data') or []
        if len(hr_data) >= 12:
            third = len(hr_data) // 3
            first_avg = sum(hr_data[:third]) / third
            last_avg  = sum(hr_data[-third:]) / third
            drift = last_avg - first_avg
            if drift > 5:
                hr_line += f' | HR drifted +{drift:.0f}bpm first→last third (cardiac drift)'
            elif drift < -5:
                hr_line += f' | HR fell {abs(drift):.0f}bpm first→last third (fading effort / pacing off)'
    except Exception:
        log.debug('HR drift for the AI prompt failed', exc_info=True)
    return hr_line + '\n'


def _current(activity, p):
    """The activity's own figures, as the sport reads them: pace on foot and in the water, speed on a bike, no distance for a strength session."""
    from services import units
    mins = int(activity['movingTime'] or 0) // 60
    current = f'"{activity["name"]}" — {str(activity["startDateLocal"])[:10]}\n'
    current += f'  Sport      : {p.label}{" (indoors)" if p.indoor and "ndoor" not in p.label else ""}\n'
    if p.distance and activity['distance']:
        dist = units.fmt_dist(activity['distance']) if p.rate != 'swim' else '{:,.0f} m'.format(float(activity['distance']))     # a pool is in metres
        current += f'  Distance   : {dist}\n'
    current += f'  Moving time: {mins} min\n'
    if p.distance and activity['averageSpeed']:
        label = 'Avg speed  ' if p.rate == 'speed' else 'Avg pace   '
        current += f'  {label}: {units.fmt_rate(activity["averageSpeed"], p.rate)}\n'
    if p.climbing and activity['totalElevationGain']:
        current += f'  Elevation  : {units.fmt_elev(activity["totalElevationGain"])}\n'
    if activity['averageWatts']:
        current += f'  Avg power  : {activity["averageWatts"]:.0f} W'
        if activity['weightedAvgWatts']:
            current += f' (NP: {activity["weightedAvgWatts"]:.0f} W)'
        current += '\n'
    if activity['averageHeartrate']:
        current += _hr_line(activity)
    if activity['averageCadence'] and p.cadence:
        unit, factor = p.cadence
        current += f'  Avg cadence: {activity["averageCadence"] * factor:.0f} {unit}\n'
    if activity['calories']:
        current += f'  Calories   : {activity["calories"]:.0f} kcal\n'
    return current


def _weather_rule(p):
    """What the weather means for this sport's numbers."""
    from services import units
    if p.indoor:
        return None
    if p.family == 'ride':
        return ("WEATHER: if conditions data is present and shows wind, cold, heat, or rain — factor it into your speed/power interpretation before "
                "drawing any conclusions about effort. A 13mph headwind ride that looks slow may be a stronger effort than a calm day at 14mph")
    if p.rate == 'pace':
        return ("WEATHER: heat, humidity, strong wind and wet or icy ground all slow the pace and raise the heart rate for the same effort. "
                "Factor them in before reading a slower pace as lost fitness")
    if 'surf' in p.sport.lower() or 'foil' in p.sport.lower():
        return ("WEATHER: the wind and the conditions are what the session was made of. Read the speed and distance against them, "
                "not against a calm day")
    return ("WEATHER: if conditions data is present and shows wind, cold, heat, or rain, say what it means for the numbers before attributing "
            "changes to fitness or fatigue")


def generate_analysis(activity, personality_key=None):
    chat = get_chat()
    if chat is None:
        raise AIUnavailable(missing_key_message('to enable AI coaching'))

    from services import units                         # the coach reads every number in the rider's own units
    from services.coach_sports import profile
    from services.context import build_context, build_comparison_receipts, get_weather_line
    p = profile(activity['sportType'])

    settings = query_db('SELECT coachingGoals, coachPersonality FROM Settings WHERE id=1', one=True)
    goals = (settings['coachingGoals'] or '').strip() if settings else ''
    if personality_key is None:
        personality_key = (settings['coachPersonality'] or 'default') if settings else 'default'
    personality = PERSONALITIES.get(personality_key, PERSONALITIES['default'])

    rider_name = 'the athlete'
    if activity['riderId']:
        rider_row = query_db('SELECT name FROM Rider WHERE id=?', [activity['riderId']], one=True)
        if rider_row:
            rider_name = rider_row['name']

    words = {'rider_name': rider_name, 'sport': p.sport_word, 'session': p.noun, 'athlete': p.athlete}
    framing = personality['framing'].format(**words)
    tone_extra = personality['tone_override'].format(**words) if personality['tone_override'] else None

    current = _current(activity, p)
    weather_line = get_weather_line(activity)
    if weather_line:
        current += f'  Conditions : {weather_line}\n'
    if activity['description']:
        current += f'  Description: {activity["description"].strip()}\n'
    if activity['notes']:
        current += f'  Athlete\'s notes: {activity["notes"]}\n'

    context          = build_context(activity)
    receipts         = build_comparison_receipts(activity)
    receipts_section = _format_receipts(receipts)

    noun, nouns = p.noun, p.nouns
    rate_word = {'speed': 'speed', 'pace': 'pace', 'swim': 'pace per 100 m'}.get(p.rate)
    measures = '/'.join(x for x in ('power' if p.family == 'ride' else None, rate_word, 'heart rate') if x)
    weather_rule = _weather_rule(p)

    system_msg = framing + '\n'
    system_msg += f'\nThis is a {noun} ({p.label}). Coach it as {p.sport_word}, in its own terms: '
    if p.distance:
        system_msg += f'its {rate_word}, heart rate{", power" if p.family == "ride" else ""}{", climbing" if p.climbing else ""} and how they relate.'
    else:
        system_msg += ('it records time, heart rate and calories, and anything in the notes. There is no distance, pace or speed: '
                       'never invent them, and never fault the session for not having them.')
    system_msg += f' Compare it with the athlete\'s other {nouns}, not with other sports.\n'
    if goals:
        system_msg += f'\nTHE ATHLETE\'S CURRENT GOALS (factor these into your analysis where relevant):\n{goals}\n'
    system_msg += f"""
TONE (non-negotiable):
- {"Personality note: " + tone_extra if tone_extra else "Sound like a knowledgeable training mate who has actually looked at the numbers — not a fitness app generating a structured report"}
- Be observational. Interpret what numbers mean, not just what they are
- Be honest about current form — if pacing was off, fatigue is showing, or the numbers were below recent efforts, say so plainly. Base this on recent {nouns} (last few weeks/months), not historical peaks
- If the athlete's goals mention a comeback or return from a break: judge performance against their current trajectory, not their pre-break best. Someone rebuilding from scratch doing a reasonable training {noun} is NOT having a poor {noun} just because it's slower than their peak from years ago
- Historical PRs (marked as "historical — aspirational target") show what's been achieved before. Use them as context for the ceiling, not as a stick to beat current performance with. Never say a {noun} was poor solely because it's slower than a years-old PR
- THE ATHLETE'S NOTES AND DESCRIPTION: if they've added notes (visible in the current {noun}'s data), treat them as ground truth about its intent. "Chilled ride with son", "recovery spin", "easy jog", "deliberately easy" = intentional low effort — do NOT critique {measures} as if they were trying hard. Acknowledge the intent and assess whether the {noun} delivered what it was meant to. Similarly "GPS dropped" or "bad data" notes should stop you treating incomplete stats as representative
- OTHER TRAINING: the history lists the athlete's other sports in the weeks before. Use it to read fatigue and load — a hard run or a heavy gym session the day before explains tired legs today — but never compare this {noun}'s numbers with another sport's
- ACKNOWLEDGE GAINS: if the history begins with a "Comeback progress by month" table — READ THIS FIRST. Read the OVERALL ARC from the first month to the most recent complete month (ignore any month flagged as partial — partial months have too few sessions to compare fairly). If the overall arc shows {measures} improving, name those specific numbers. This is the most important context for a comeback and must appear in the bigger picture section. NEVER call a partial month's average a "downturn" compared to a prior full month — that is noise, not signal. Don't skip the comeback table in favour of micro-comparisons between individual {nouns}"""
    if weather_rule:
        system_msg += f'\n- {weather_rule}'
    system_msg += f"""

BANNED WORDS AND PHRASES — you must not use any of these, even once:
solid, decent, great effort, commendable, considerable, promising, developing well, well done, good job, maintain consistency, keep it up, respectable, your body is adapting, impressive, well-executed, nicely done, moving forward, moving in the right direction, on the right track, heading in the right direction, stay focused, keep pushing, step up, step forward, notable progression, good progress, great progress, positive ride, positive session

Before you output your response, scan it for every word above. If you find one, replace it with a direct observation or cut the sentence.

OTHER RULES:
- Never pad a section with generic observations — skip the section instead
- Don't restate stats without interpretation: not the bare number but what it means given the terrain, the conditions, and the previous {nouns}
- Express deltas naturally: "17:26 faster", "about 24% quicker", "same heart rate, quicker pace" — never raw seconds, never "improved by -Xs"
- Reduce certainty: not "all clear, no fatigue" but "nothing obviously concerning, though hard to say from one {noun}"
- Occasionally challenge how the athlete probably felt vs what the data actually shows"""
    if not p.indoor:
        system_msg += ('\n- If conditions show wind, adverse weather, cold, or heat: explain what that means for the numbers before attributing '
                       'changes to fitness or fatigue')

    user_msg = f"""CURRENT {noun.upper()}:
{current}
HISTORY & CONTEXT:
{context}
"""
    if receipts_section:
        user_msg += f"""
COMPARISON EVIDENCE — use at least 2-4 of these in your analysis. Quote specific dates, times, and deltas. Don't paraphrase vaguely:
{receipts_section}
"""
    optional = []
    if p.climb_limit_m:
        optional.append(f'⛰️ Climbing — only if elevation > {units.fmt_elev(p.climb_limit_m)} and the climbing meaningfully changes what the numbers mean')
    optional.append(f'🔥 Standout metric — only if there is a genuinely interesting {measures} relationship worth explaining')
    optional.append('📈 Fitness reading — only if you can say something specific about adaptation or trajectory, not just "numbers are up"')
    if not p.indoor:
        optional.append('🌦️ Conditions — only if weather was a real factor that changes how the numbers should be read')
    optional.append('🏁 Segments — only if segment or comparison data exists; use specific dates and deltas from the evidence')
    optional.append(f'🏆 Achievements — only if best efforts or badges were set on this {noun}')
    optional.append('🚨 Warning — only if you see something genuinely concerning; don\'t invent warnings to fill space')
    optional.append('🔮 Trajectory — only if the pattern is specific enough to make a realistic projection')
    optional_lines = '\n'.join(optional)

    user_msg += f"""---

Write coaching notes, not a report. Use emoji headers for each section.

REQUIRED — always write these three:
{p.icon} The {noun} — 1-2 sentences. What actually happened. One sharp observation, not a stat summary.
🧩 Bigger picture — 2-4 sentences. How this sits against the recent pattern of {nouns} and the rest of the athlete's training. If comparison evidence exists, use specific dates and deltas — make progress (or regression) concrete.
🎯 Honest verdict — 1-2 sentences. Was this a good day, a poor day, or somewhere in between? Say it plainly.

OPTIONAL — include only if you have something specific and non-obvious to say. Skip entirely otherwise:
{optional_lines}

Close with a single plain sentence (no emoji, no header). A specific observation from this {noun}'s data only — a fact, a number, a pattern that's worth knowing. NOT an instruction for next time. NOT "keep X going", "focus on Y", "work on Z", or any sentence that tells the athlete what to do next. If it could appear on any generic summary, rewrite it.

RULES:
- Skip optional sections rather than fill them with generic observations
- If comparison evidence was provided: use at least 2-4 specific receipts with dates and deltas
- If a {noun} was genuinely below recent form: say so and explain what's behind it. If it was a reasonable training {noun} given the pattern and conditions, say that instead
- If no history exists: analyse the data alone and flag it
- The final sentence must be specific to this {noun} — if it could apply to any {noun} on any day, rewrite it"""

    system_msg = units.localise(system_msg)      # its worked example ('a 13mph headwind ride') in the rider's units too

    return chat([{'role': 'user', 'content': user_msg}], system=system_msg, max_tokens=1000, temperature=0.7)


def ensure_weather(db, activity):
    """The activity with its weather fetched and stored, when it has none yet (the analysis reads it). Commits."""
    if activity['weatherSummary'] or not activity['startLat'] or not activity['startLng']:
        return activity
    try:
        from services.weather import fetch_weather, save_weather
        w = fetch_weather(
            activity['startLat'],
            activity['startLng'],
            activity['startDateLocal'],
            activity['streams'],
            activity['sportType'],
        )
        if w:
            save_weather(db, activity['id'], w)
            db.commit()
            return query_db(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [activity['id']], one=True)
    except Exception:
        log.warning('Weather fetch before the AI analysis failed', exc_info=True)
    return activity


def analyse_ride(db, activity, personality_key=None):
    """Everything 'analyse this activity' does, for the activity page's button, the AI page's batch and the analysis of new activities
    (services/auto_analyse.py), for every sport: weather if it has none, the analysis, stored on the activity and in its ActivityMemory. Returns the text;
    raises when there is no provider or it fails. Commits."""
    activity = ensure_weather(db, activity)
    text = generate_analysis(activity, personality_key=personality_key)
    db.execute(
        "UPDATE Activity SET aiKudos=?, aiKudosAt=datetime('now') WHERE id=?",
        [text, activity['id']],
    )
    db.commit()
    from services.context import save_ride_memory
    save_ride_memory(activity, text)
    return text


# backward-compat alias used by webhook.py
generate_kudos = generate_analysis
