import json
import re
from pathlib import Path
from urllib.parse import quote

from ..errors import ApiError

HOSTS = {
    "youtube": "https://youtube.googleapis.com",
    "x": "https://api.x.com",
    "steam": "https://api.steampowered.com",
}


def invalid(message="Check the documented operation parameters."):
    return ApiError(422, "invalid_request", message)


class Catalog:
    def __init__(self, directory: Path):
        self.providers = {}
        for provider, host in HOSTS.items():
            doc = json.loads((directory / f"{provider}.json").read_text())
            for operation in doc["operations"].values():
                store_operation = (
                    provider == "steam"
                    and operation["base_url"] == "https://store.steampowered.com"
                    and operation["path"]
                    == {
                        "store.appdetails": "/api/appdetails",
                        "store.search": "/api/storesearch/",
                        "store.recommendations": "/recommended/morelike/app/",
                    }.get(operation["id"])
                )
                if (
                    (operation["base_url"] != host and not store_operation)
                    or operation["method"] != "GET"
                    or not operation["path"].startswith("/")
                    or operation["path"].startswith("//")
                ):
                    raise ValueError("Unsafe provider catalog")
            self.providers[provider] = doc

    def document(self, provider):
        if provider not in self.providers:
            raise ApiError(404, "unknown_provider", "Provider is not registered.")
        return self.providers[provider]

    def resolve(self, provider, name):
        doc = self.document(provider)
        if name not in doc["operations"]:
            raise ApiError(
                404, "unknown_operation", "Read operation is not registered."
            )
        return doc["operations"][name]

    def schema(self, provider, schema):
        definitions = self.document(provider)["schemas"]
        seen = set()
        while "$ref" in schema and schema["$ref"] not in seen:
            ref = schema["$ref"]
            seen.add(ref)
            path = (
                ref.removeprefix("#/components/").split("/")
                if ref.startswith("#/")
                else [ref]
            )
            schema = definitions
            for part in path:
                schema = schema.get(part, {})
        return schema

    def describe(self, provider, name):
        operation = self.resolve(provider, name)
        definitions = {}

        def collect(node):
            if isinstance(node, dict):
                if "$ref" in node and node["$ref"] not in definitions:
                    ref = node["$ref"]
                    definitions[ref] = self.schema(provider, node)
                    collect(definitions[ref])
                for key, value in node.items():
                    if key != "$ref":
                        collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(operation)
        doc = self.document(provider)
        return {
            **operation,
            "definitions": definitions,
            "source_url": operation.get("source_url", doc["source_url"]),
            "verified_date": doc["verified_date"],
        }

    def prepare(self, provider, name, params):
        operation = self.resolve(provider, name)
        if operation["availability"] == "unsupported":
            raise ApiError(
                400,
                "unsupported_operation",
                "This stream, media or session operation is not supported.",
            )
        if operation["availability"] == "requires-authorization":
            raise ApiError(
                403,
                "provider_authorization_required",
                "This operation requires additional company-side user authorization.",
            )
        declared = operation["parameters"]
        normalized = {}
        for key in params:
            exemplar = re.sub(r"\[(?:0|[1-9][0-9]*)\]$", "[0]", key)
            normalized[key] = key if key in declared else exemplar
        if set(normalized.values()) - set(declared):
            raise invalid(
                "Unknown or server-managed parameter. Use describe to inspect this operation."
            )
        if any(
            p.get("required") and (name not in params or params[name] is None)
            for name, p in declared.items()
        ):
            raise invalid("A required operation parameter is missing.")
        if provider == "youtube" and any(
            params.get(key) not in (None, False, "false")
            for key in (
                "mine",
                "forMine",
                "forContentOwner",
                "onBehalfOfContentOwner",
                "onBehalfOfContentOwnerChannel",
            )
        ):
            raise ApiError(
                403,
                "provider_authorization_required",
                "Account-private filters require user OAuth authorization.",
            )
        path = operation["path"]
        query = {}
        for key, value in params.items():
            parameter = declared[normalized[key]]
            schema = self.schema(provider, parameter.get("schema", parameter))
            if value is None:
                raise invalid()
            values = value if isinstance(value, list) else [value]
            if not values or any(isinstance(item, (dict, list)) for item in values):
                if operation.get("transport_mode") != "input_json":
                    raise invalid()
            if "enum" in schema and any(item not in schema["enum"] for item in values):
                raise invalid("Parameter value is not in the documented enum.")
            expected = schema.get("type", "")
            if expected == "boolean" and value not in (True, False, "true", "false"):
                raise invalid()
            if expected in {"integer", "uint32", "uint64", "int32", "int64"}:
                if isinstance(value, bool) or not str(value).lstrip("-").isdigit():
                    raise invalid()
                if (
                    "minimum" in schema
                    and int(value) < int(schema["minimum"])
                    or "maximum" in schema
                    and int(value) > int(schema["maximum"])
                ):
                    raise invalid("Parameter is outside the documented range.")
            if parameter.get("location") == "path":
                if (
                    not isinstance(value, (str, int))
                    or any(char in str(value) for char in ("/", "\\", "?", "#", "%"))
                    or str(value) in {".", "..", ""}
                ):
                    raise invalid("Invalid path parameter.")
                path = path.replace("{" + key + "}", quote(str(value), safe=""))
            else:
                query[key] = value
        return operation, path, query
