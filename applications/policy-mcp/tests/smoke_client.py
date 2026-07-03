import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


MCP_URL = os.getenv(
    "MCP_URL",
    "http://policy-mcp:8080/mcp",
)


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

            result = await session.call_tool(
                "search_policies",
                arguments={
                    "airline": "fedora-air",
                    "disruption_type": "weather",
                    "travel_date": "2027-01-15",
                    "event_id": "crimson-storm",
                },
            )

            print("\nSearch result:")

            for content in result.content:
                text = getattr(content, "text", None)

                if text:
                    try:
                        print(
                            json.dumps(
                                json.loads(text),
                                indent=2,
                            )
                        )
                    except json.JSONDecodeError:
                        print(text)


if __name__ == "__main__":
    asyncio.run(main())