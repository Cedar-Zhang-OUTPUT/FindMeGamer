import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
