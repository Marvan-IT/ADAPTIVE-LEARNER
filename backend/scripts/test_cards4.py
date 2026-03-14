import asyncio, sys, json, re
sys.path.insert(0, 'src')
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI
from openai import AsyncOpenAI
from api.prompts import build_cards_system_prompt, build_cards_user_prompt
from api.knowledge_service import KnowledgeService
from api.teaching_service import TeachingService

def fix_json_escapes(s):
    """Fix invalid backslash escapes from LaTeX in JSON strings."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)

async def main():
    ks = KnowledgeService()
    concept = ks.get_concept_detail('PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS')
    concept_text = concept['text']
    concept_title = concept['concept_title']
    latex = concept.get('latex', [])

    sub_sections = TeachingService._parse_sub_sections(concept_text)
    if not sub_sections:
        sub_sections = [{'title': concept_title, 'text': concept_text}]
    else:
        sub_sections = TeachingService._group_by_major_topic(sub_sections)

    for s in sub_sections:
        if len(s['text']) > 500:
            s['text'] = s['text'][:500] + '...'

    sys_p = build_cards_system_prompt('default')
    user_p = build_cards_user_prompt(concept_title=concept_title, sub_sections=sub_sections, latex=latex)

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    r = await client.chat.completions.create(
        model=OPENAI_MODEL_MINI,
        messages=[{'role': 'system', 'content': sys_p}, {'role': 'user', 'content': user_p}],
        max_tokens=4000,
        timeout=120.0,
    )
    content = r.choices[0].message.content
    print(f'Finish: {r.choices[0].finish_reason} | Tokens: {r.usage.completion_tokens}')

    # Extract JSON block
    if '```' in content:
        m = re.search(r'```(?:json)?\s*(.*?)```', content, re.DOTALL)
        if m:
            content = m.group(1).strip()

    # Apply fix
    fixed = fix_json_escapes(content)

    try:
        data = json.loads(fixed)
        cards = data.get('cards', [])
        print(f'SUCCESS! Cards: {len(cards)}')
        for c in cards:
            print(f'  [{c.get("card_type")}] {str(c.get("title",""))[:50]}')
    except json.JSONDecodeError as e:
        pos = e.pos
        print(f'JSON error at {pos}: {e.msg}')
        print(f'Raw around pos: {repr(content[max(0,pos-30):pos+30])}')
        print(f'Fixed around pos: {repr(fixed[max(0,pos-30):pos+30])}')

asyncio.run(main())
