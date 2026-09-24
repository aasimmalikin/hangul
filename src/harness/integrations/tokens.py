"""``user-token:<source>`` references in MCP server config: resolved to a
real bearer token for one user, at connect time, by the named source.
Unlike ``vault:`` refs (grants for our own proxy) these are the third
party's own tokens -- the MCP server *is* the third party."""

from harness.integrations.google_oauth import google_tokens

PREFIX = "user-token:"


async def resolve_user_token(source: str, subject: str) -> str:
    if source.startswith("google"):
        product = source.split(":", 1)[1] if ":" in source else None
        return await google_tokens().access_token(subject, product=product)
    raise ValueError(f"unknown user-token source {source!r}")


def has_user_token_refs(values: dict[str, str] | None) -> bool:
    return any(PREFIX in v for v in (values or {}).values())


async def substitute(values: dict[str, str] | None, subject: str) -> dict[str, str] | None:
    if not values:
        return values
    out = {}
    for k, v in values.items():
        while PREFIX in v:
            i = v.index(PREFIX)
            j = i + len(PREFIX)
            k2 = j
            while k2 < len(v) and (v[k2].isalnum() or v[k2] in "_-:."):
                k2 += 1
            v = v[:i] + await resolve_user_token(v[j:k2], subject) + v[k2:]
        out[k] = v
    return out
