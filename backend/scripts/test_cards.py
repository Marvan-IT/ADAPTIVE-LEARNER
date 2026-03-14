import asyncio, sys, json, re
sys.path.insert(0, 'src')
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI
from openai import AsyncOpenAI
from api.prompts import build_cards_system_prompt, build_cards_user_prompt
from api.knowledge_service import KnowledgeService
from api.teaching_service import TeachingService

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
    print(f'Sections: {len(sub_sections)}')

    sys_p = build_cards_system_prompt('default')
    user_p = build_cards_user_prompt(
        concept_title=concept_title,
        sub_sections=sub_sections,
        latex=latex,
        images=images,
    )
    print(f'Prompt: sys={len(sys_p)} user={len(user_p)}')

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    r = await client.chat.completions.create(
        model=OPENAI_MODEL_MINI,
        messages=[{'role': 'system', 'content': sys_p}, {'role': 'user', 'content': user_p}],
        max_tokens=6000,
        timeout=120.0,
    )
    content = r.choices[0].message.content
    print(f'Finish: {r.choices[0].finish_reason} | Usage: {r.usage}')
    print(f'Response length: {len(content)} chars')

    # Extract JSON
    if '```' in content:
        m = re.search(r'```(?:json)?\s*(.*?)```', content, re.DOTALL)
        if m:
            content = m.group(1).strip()

    try:
        data = json.loads(content)
        cards = data.get('cards', [])
        print(f'Cards parsed: {len(cards)}')
        for c in cards:
            print(f'  [{c.get("card_type")}] {c.get("title", "")[:50]}')
    except json.JSONDecodeError as e:
        print(f'JSON error: {e}')
        print(f'Last 300 chars: {content[-300:]}')

asyncio.run(main())
