from langchain_core.messages import HumanMessage

from bot.agent.contracts import AgentResponse
from bot.agent.graph import agent_graph
from bot.agent.runtime import AgentRuntimeContext, current_agent_context


async def run_agent_message(
    user_id: str,
    message: str,
    channel: str,
) -> AgentResponse:
    config = {"configurable": {"thread_id": user_id}, "recursion_limit": 8}
    runtime_token = current_agent_context.set(
        AgentRuntimeContext(user_id=user_id, channel=channel)
    )
    try:
        result = await agent_graph.ainvoke(
            input={
                "messages": [HumanMessage(content=message)],
                "user_id": user_id,
                "channel": channel,
            },
            config=config,
        )
    finally:
        current_agent_context.reset(runtime_token)

    if result.get("response"):
        response = result["response"]
        if isinstance(response, AgentResponse):
            return response
        return AgentResponse.model_validate(response)

    return AgentResponse(message=result["messages"][-1].content)
