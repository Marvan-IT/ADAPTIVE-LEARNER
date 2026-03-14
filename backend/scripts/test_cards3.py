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

    sub_sections = TeachingService._parse_sub_sections(concept_text)
    if not sub_sections:
        sub_sections = [{'title': concept_title, 'text': concept_text}]
    else:
        sub_sections = TeachingService._group_by_major_topic(sub_sections)

    # Truncate each section text
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

    # Show what's around char 1790
    print(f'Chars 1750-1850: {repr(content[1750:1850])}')

asyncio.run(main())
