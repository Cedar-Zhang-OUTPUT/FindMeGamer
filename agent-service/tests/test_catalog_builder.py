def test_youtube_builder_only_registers_read_operations():
    from fmg_agent.providers.build_catalogs import youtube_catalog

    doc = {
        "rootUrl": "https://youtube.googleapis.com/",
        "parameters": {"key": {"type": "string"}},
        "schemas": {},
        "resources": {
            "search": {
                "methods": {
                    "list": {
                        "httpMethod": "GET",
                        "path": "youtube/v3/search",
                        "parameters": {
                            "part": {
                                "type": "string",
                                "required": True,
                                "location": "query",
                            },
                            "pageToken": {"type": "string"},
                        },
                        "response": {},
                    }
                }
            },
            "videos": {
                "methods": {
                    "delete": {"httpMethod": "DELETE", "path": "youtube/v3/videos"}
                }
            },
        },
    }
    catalog = youtube_catalog(doc)
    assert list(catalog["operations"]) == ["search.list"]
    operation = catalog["operations"]["search.list"]
    assert "key" not in operation["parameters"]
    assert operation["pagination"]["request_param"] == "pageToken"
    assert operation["pagination"]["response_path"] == ["nextPageToken"]


def test_x_preserves_fields_params_and_auth_requirements():
    from fmg_agent.providers.build_catalogs import x_catalog

    doc = {
        "components": {},
        "paths": {
            "/2/users/{id}": {
                "get": {
                    "operationId": "getUsersById",
                    "security": [{"BearerToken": []}],
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "user.fields",
                            "in": "query",
                            "schema": {"type": "array", "items": {"type": "string"}},
                        },
                    ],
                    "responses": {},
                }
            },
            "/2/users/me": {
                "get": {
                    "operationId": "getUsersMe",
                    "security": [{"OAuth2UserToken": ["users.read"]}],
                    "responses": {},
                }
            },
        },
    }
    catalog = x_catalog(doc)
    assert (
        catalog["operations"]["getUsersById"]["parameters"]["user.fields"]["schema"][
            "type"
        ]
        == "array"
    )
    assert (
        catalog["operations"]["getUsersMe"]["availability"] == "requires-authorization"
    )


def test_steam_get_heartbeat_is_not_treated_as_read():
    from fmg_agent.providers.build_catalogs import steam_catalog

    doc = {
        "apilist": {
            "interfaces": [
                {
                    "name": "ISteamBroadcast",
                    "methods": [
                        {
                            "name": "ViewerHeartbeat",
                            "version": 1,
                            "httpmethod": "GET",
                            "parameters": [],
                        }
                    ],
                },
                {
                    "name": "ISteamNews",
                    "methods": [
                        {
                            "name": "GetNewsForApp",
                            "version": 2,
                            "httpmethod": "GET",
                            "parameters": [
                                {"name": "appid", "type": "uint32", "optional": False}
                            ],
                        }
                    ],
                },
            ]
        }
    }
    catalog = steam_catalog(doc)
    assert (
        catalog["operations"]["ISteamBroadcast.ViewerHeartbeat.v1"]["availability"]
        == "unsupported"
    )
    assert (
        catalog["operations"]["ISteamNews.GetNewsForApp.v2"]["parameters"]["appid"][
            "required"
        ]
        is True
    )
