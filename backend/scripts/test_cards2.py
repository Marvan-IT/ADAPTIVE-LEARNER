import asyncio, sys, json, re
sys.path.insert(0, 'src')
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI
from openai import AsyncOpenAI
from api.prompts import build_cards_system_prompt, build_cards_user_prompt
from api.knowledge_service import KnowledgeService
from api.teaching_service import TeachingService

def fix_json_escapes(s):
    """Fix invalid backslash escapes from LaTeX in JSON strings."""
    # Replace \x where x is not a valid JSON escape char
    return re.sub(r'\\(?!["\\/bfnrtu\n])', r'\\\\', s)

async def main():
    ks = KnowledgeService()
    concept = ks.get_concept_detail('PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS')
    concept_text = concept['text']
    concept_title = concept['concept_title']
    latex = concept.get('latex', [])
    images = concept.get('images', [])

    sub_sections = TeachingService._parse_sub_sections(concept_text)
    if not sub_sections:
        sub_sections = [{'title': concept_title, 'text': concept_text}]
    else:
        sub_sections = TeachingService._group_by_major_topic(sub_sections)

    # Truncate each section text to 500 chars to reduce prompt size
    for s in sub_sections:
        if len(s['text']) > 500:
            s['text'] = s['text'][:500] + '...'

    sys_p = build_cards_system_prompt('default')
    user_p = build_cards_user_prompt(
        concept_title=concept_title,
        sub_sections=sub_sections,
        latex=latex,
        images=images,
    )
    print(f'Sections: {len(sub_sections)} | Prompt: sys={len(sys_p)} user={len(user_p)}')

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    import time
    t0 = time.time()
    r = await client.chat.completions.create(
        model=OPENAI_MODEL_MINI,
        messages=[{'role': 'system', 'content': sys_p}, {'role': 'user', 'content': user_p}],
        max_tokens=4000,
        timeout=120.0,
    )
    elapsed = time.time() - t0
    content = r.choices[0].message.content
    print(f'Finish: {r.choices[0].finish_reason} | Usage: {r.usage} | Time: {elapsed:.1f}s')
    print(f'Response length: {len(content)} chars')

    # Extract JSON block
    if '```' in content:
        m = re.search(r'```(?:json)?\s*(.*?)```', content, re.DOTALL)
        if m:
            content = m.group(1).strip()

    # Fix LaTeX backslash escapes
    fixed = fix_json_escapes(content)

    try:
        data = json.loads(fixed)
        cards = data.get('cards', [])
        print(f'Cards parsed: {len(cards)}')
        for c in cards:
            print(f'  [{c.get("card_type")}] {str(c.get("title", ""))[:50]}')
    except json.JSONDecodeError as e:
        print(f'JSON error: {e}')
        # Show problematic area
        pos = e.pos
        print(f'Context around error: ...{fixed[max(0,pos-50):pos+50]}...')

asyncio.run(main())
