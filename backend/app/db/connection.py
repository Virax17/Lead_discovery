import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from app.config.settings import settings


class Database:
    client: AsyncIOMotorClient = None
    db = None


db_ctx = Database()


def get_db():
    if db_ctx.client is None:
        db_ctx.client = AsyncIOMotorClient(
            settings.mongo_uri,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=30000,
        )
        db_ctx.db = db_ctx.client[settings.mongo_db_name]
    return db_ctx.db
