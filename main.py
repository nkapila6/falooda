#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-12-20 10:55:29 Saturday

@author: Nikhil Kapila
"""

import asyncio, json, re
from pathlib import Path
from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.workflow import Workflow
from agno.tools.mcp import MCPTools

# custom instruction prompts
from agent_prompts import story_ideator_prompt
from agent_prompts import story_writer_prompt
from agent_prompts import web_search_prompt

model_name_web_search = "PetrosStav/gemma3-tools:4b"
model_name_story = "adi0adi/ollama_stheno-8b_v3.1_q6k"
mcp_local_rag = MCPTools(
    command="uvx --python=3.10 --from git+https://github.com/nkapila6/mcp-local-rag mcp-local-rag",
    timeout_seconds=60
)
debug = False

AGE_GROUPS_GENRES = {
    "0_2": [
        "animals",
        "daily_life",
        "comfort",
        "nature",
        "soft_magic"
    ],
    "3_6": [
        "animals",
        "kindness",
        "friendship",
        "curiosity",
        "creativity",
        "gratitude",
        "nature",
        "fantasy",
        "soft_magic",
        "daily_life"
    ],
    "7_plus": [
        "animals",
        "courage",
        "friendship",
        "curiosity",
        "creativity",
        "gratitude",
        "nature",
        "fantasy",
        "adventure",
        "life_lessons",
        "space",
        "problem_solving"
    ]
}
STORIES_PER_COMBINATION = 5

def parseout_json(text:str)->dict:
    if "```" in text:
        text = text.split("```")
    text = text[1][4:].strip()
    return json.loads(text)

def mcp_toolcall_repack(text)->list:
    # json from mcp
    js = json.loads(text.content[0].text) #js is of type list
    output = []
    for item in js['content']:
        result={} #item is a dict, limit to 500 chars
        result['text'], result['url'] = item['text'][0:500], item['url']
        output.append(result)

    return result

def sanitize_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = text.replace(' ', '_')
    text = text[:100]
    text = text.strip('. ') # remove leading/trailing whitespace and dots
    return text

def save_story(story_content: str, age_group: str, genre: str, story_number: int):
    # output/age_group/genre/
    folder_path = Path("output") / age_group / genre
    folder_path.mkdir(parents=True, exist_ok=True)
    
    # try getting json out
    try:
        story_json = parseout_json(story_content)
        title = story_json.get('title', f'story_{story_number}')
        # add age group, genre, and story number to the JSON
        story_json['age_group'] = age_group
        story_json['genre'] = genre
        story_json['story_number'] = story_number
        story_data = story_json
    except (json.JSONDecodeError, KeyError, IndexError):
        title = f'story_{story_number}'
        story_data = {
            "age_group": age_group,
            "genre": genre,
            "story_number": story_number,
            "content": story_content
        }
    
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}_{story_number}.json"
    filepath = folder_path / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(story_data, f, indent=2, ensure_ascii=False)
    
    print(f"Saved story to: {filepath}")
    return filepath

def make_agents(age_group:str, genre:str):
    instructions_web = web_search_prompt.format(age_group=age_group, genre=genre)
    instructions_idea = (story_ideator_prompt.replace("{age_group}", age_group).replace("{genre}", genre))
    instructions_write = story_writer_prompt.format(age_group=age_group, genre=genre)

    web_searcher = Agent(
        name="Web Searcher",
        instructions=instructions_web,
        model=Ollama(id=model_name_web_search),
        debug_mode=debug,
        markdown=False,
    )
    story_ideator = Agent(
        name="Story Ideator",
        instructions=instructions_idea,
        model=Ollama(id=model_name_story),
        debug_mode=debug,
        markdown=False,
    )
    story_writer = Agent(
        name="Story Writer",
        instructions=instructions_write,
        model=Ollama(id=model_name_story),
        debug_mode=debug,
        markdown=False,
    )
    return web_searcher, story_ideator, story_writer

class StoryFlow(Workflow):
    async def run(self, age_group: str = "0-2", genre: str = "animals"):
        web_searcher, story_ideator, story_writer = make_agents(age_group, genre)
        queries = await web_searcher.arun(f"Generate 3 search queries to make stories for age_group {age_group} and genre {genre}")
        queries = json.loads(queries.content.split("```")[1][4:])
        # print(queries)
        
        # parse llm queries to perform search, get urls and content
        # some assumptions since this is being done locally on Ollamaaa: 1. taking only 500 chars instead of 10k, 2. taking only first 2 queries instead of 3-5 that the tool call would return.
        results = []
        for query in queries["queries"][:2]:
            result = await mcp_local_rag.session.call_tool("rag_search", {"query": query})
            results.append(mcp_toolcall_repack(result))
        # print(results)

        # generating story idea here
        ideation_prompt = f"The search results are as follows. You need to ideate a single story from the search results.\n\n{results}"
        ideation = await story_ideator.arun(ideation_prompt)

        # # finally write story!
        story = await story_writer.arun(ideation.content)
        return story.content

async def main():
    await mcp_local_rag.connect()

    try:
        content_workflow = StoryFlow(name="Story Writer")
        total_combinations = sum(len(genres) for genres in AGE_GROUPS_GENRES.values())
        total_stories = total_combinations * STORIES_PER_COMBINATION
        current_story = 0
        
        print(f"Starting story generation: {total_stories} total stories")
        print(f"({total_combinations} combinations × {STORIES_PER_COMBINATION} stories each)\n")
        
        for age_group, genres in AGE_GROUPS_GENRES.items():
            for genre in genres:
                print(f"\n{'='*60}")
                print(f"Generating stories for Age Group: {age_group}, Genre: {genre}")
                print(f"{'='*60}")
                
                for story_num in range(1, STORIES_PER_COMBINATION + 1):
                    current_story += 1
                    print(f"\n[{current_story}/{total_stories}] Generating story {story_num}/{STORIES_PER_COMBINATION} for {age_group}/{genre}...")
                    
                    try:
                        # generating
                        result = await content_workflow.run(age_group=age_group, genre=genre)
                        
                        # saving
                        filepath = save_story(result, age_group, genre, story_num)
                        print(f"✓ Successfully saved: {filepath}")
                        
                    except Exception as e:
                        print(f"✗ Error generating story {story_num} for {age_group}/{genre}: {e}")
                        continue
        
        print(f"\n{'='*60}")
        print("Story generation complete!")
        print(f"Total stories generated: {current_story}")
        print(f"{'='*60}")
        
    finally:
        await mcp_local_rag.close()

if __name__ == "__main__":
    asyncio.run(main())
