.PHONY: example-mcp

example-mcp:
	uv run fastmcp run example_mcp.py --transport http
