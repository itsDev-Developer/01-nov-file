#(©)Codeflix Bots (ProYato)

from aiohttp import web
from .route import routes
from .api_routes import api_routes
from .api_manage import manage_routes
from config import API_MAX_UPLOAD_MB

#===============================================================#

async def web_server(bot=None):
    # client_max_size is aiohttp's blanket request-body cap, separate from
    # (and enforced *before*) the API's own per-file check in api_routes.py.
    # It must stay >= API_MAX_UPLOAD_MB or large uploads get a bare aiohttp
    # 413 instead of the API's clearer error — sized for one big file plus
    # headroom for a multi-file batch upload.
    web_app = web.Application(client_max_size=max(30_000_000, (API_MAX_UPLOAD_MB + 50) * 1024 * 1024))
    web_app["bot"] = bot  # exposes client.mongodb / client.admins / ads config to route handlers
    web_app.add_routes(routes)
    web_app.add_routes(api_routes)
    web_app.add_routes(manage_routes)
    return web_app
