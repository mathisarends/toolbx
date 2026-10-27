import json

from pydantic import BaseModel, Field

from toolbx import Toolbox, Toolset, tool


class Filters(BaseModel):
    section: str | None = Field(default=None, description="Restrict to a section")


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)
    filters: Filters = Field(default_factory=Filters)


class DocsTools(Toolset, namespace=None):
    @tool("Search the documentation", params=SearchParams)
    def search(self, params: SearchParams) -> None:
        pass


toolbox = Toolbox(toolsets=(DocsTools(),))


def show(label: str, schema: object) -> None:
    print(f"{label}:\n{json.dumps(schema, indent=2)}\n")


def main() -> None:
    native = toolbox.schemas()[0]
    show("native", native.model_dump())
    show("anthropic", toolbox.to_anthropic()[0])
    show("openai", toolbox.to_openai()[0])
    # Strict mode: every field required, optional ones nullable.
    show("openai strict", toolbox.to_openai(strict=True)[0])
    # For providers that reject $ref/$defs.
    show("inlined", native.inline_refs().input_schema)


if __name__ == "__main__":
    main()
