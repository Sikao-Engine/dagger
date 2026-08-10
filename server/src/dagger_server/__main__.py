"""`python -m dagger_server [-c config.toml] [--host H] [--port P]` — see app.main."""

from .app import main

if __name__ == "__main__":
    main()
