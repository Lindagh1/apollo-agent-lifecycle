import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


MCP_URL = os.getenv(
    "MCP_URL",
    "http://case-management-mcp:8080/mcp",
)


async def print_result(label: str, result) -> None:
    print(f"\n{label}:")
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            try:
                print(json.dumps(json.loads(text), indent=2))
            except json.JSONDecodeError:
                print(text)


async def main() -> None:
    async with streamablehttp_client(MCP_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                print(f"- {tool.name}")

            request = await session.call_tool(
                "request_human_review",
                arguments={
                    "case_id": "APOLLO-001",
                    "policy_id": "FED-NOVA-HEALTH-EMERGENCY-2027",
                    "reason": (
                        "Emergency policy requires manual review."
                    ),
                    "queue": "health-emergency-review",
                    "recommendation": "human-review",
                },
            )
            await print_result("Human-review request", request)

            status = await session.call_tool(
                "get_case_status",
                arguments={"case_id": "APOLLO-001"},
            )
            await print_result("Case status", status)


if __name__ == "__main__":
    asyncio.run(main())
