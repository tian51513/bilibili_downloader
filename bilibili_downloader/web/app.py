import pathlib
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from bilibili_downloader.web.routes import create_routes


def create_app(db):
    app = FastAPI(title="Bilibili Downloader Dashboard")
    templates_dir = pathlib.Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    def filesizeformat(value):
        if value is None:
            return "0 B"
        value = int(value)
        for unit in ("B", "KB", "MB", "GB"):
            if abs(value) < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    templates.env.filters["filesizeformat"] = filesizeformat
    routes = create_routes(db, templates)
    for path, (handler, methods) in routes.items():
        app.add_api_route(path, handler, methods=methods)
    return app
