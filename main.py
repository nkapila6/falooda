#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on 2025-12-20 10:55:29 Saturday

@author: Nikhil Kapila
"""

import asyncio, json
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
        result = await content_workflow.run(age_group="0-2", genre="animals")
        # result = await content_workflow.run("Write a 4 paragraph story on animals for an age group of 0-2.")
        print(result)
    finally:
        await mcp_local_rag.close()

if __name__ == "__main__":
    asyncio.run(main())
