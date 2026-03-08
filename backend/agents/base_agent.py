import os
import functools
import logging
import json
import re
from groq import AsyncGroq
from graph.state import AgentReport, AgentStatus

logger = logging.getLogger(__name__)

def get_llm():
    """Build standardized Groq Client instance using the official SDK."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing.")
        
    return AsyncGroq(api_key=api_key)

import asyncio

async def call_llm_with_retry(client, messages, response_format={"type": "json_object"}, primary_model='llama-3.3-70b-versatile', fallback_model='llama-3.1-8b-instant'):
    """Calls Groq API with robust fallback to a smaller model on Rate Limit (429) errors."""
    try:
        response = await client.chat.completions.create(
            model=primary_model,
            messages=messages,
            temperature=0.1,
            response_format=response_format
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower() or "tokens" in str(e).lower():
            logger.warning(f"Rate limit hit for {primary_model}. Retrying with {fallback_model} in 3 seconds.")
            await asyncio.sleep(3)
            try:
                # Try with fallback
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    temperature=0.1,
                    response_format=response_format
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                if "429" in str(e2) or "rate limit" in str(e2).lower() or "tokens" in str(e2).lower():
                    logger.warning(f"Rate limit hit for {fallback_model}. Retrying with final fallback llama3-8b-8192 in 5 seconds.")
                    await asyncio.sleep(5)
                    response = await client.chat.completions.create(
                        model='llama3-8b-8192',
                        messages=messages,
                        temperature=0.1,
                        response_format=response_format
                    )
                    return response.choices[0].message.content.strip()
                raise e2
        raise e

def parse_llm_json(response_content: str) -> dict:
    """Robustly parse JSON from LLM response, handling markdown fences."""
    content = response_content.strip()
    
    # Remove markdown code fences
    content = re.sub(r'^```json\s*', '', content, flags=re.MULTILINE)
    content = re.sub(r'^```\s*', '', content, flags=re.MULTILINE)
    content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
    content = content.strip()
    
    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try finding JSON object within the text
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
            
    raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

def _fallback_report(agent_name: str, score: float, error: str) -> AgentReport:
    return AgentReport(
        agent_name=agent_name,
        status=AgentStatus.ERROR,
        summary=f"Analysis unavailable: {error[:100]}",
        score=score,
        key_findings=["Data temporarily unavailable"],
        risk_flags=[],
        confidence=0.0,
        data={"error": error}
    )

def agent_with_fallback(agent_name: str, default_score: float = 5.0):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, *args, **kwargs):
            try:
                return await func(state, *args, **kwargs)
            except Exception as e:
                # Let's catch JSON errors as well inside this general block
                logger.error(f"{agent_name} failed: {e}", exc_info=True)
                return _fallback_report(agent_name, default_score, str(e))
        return wrapper
    return decorator
