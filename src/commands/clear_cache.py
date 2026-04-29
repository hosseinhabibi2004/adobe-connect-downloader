import redis

from src import config


def clear_cache() -> None:
    try:
        client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True,
        )

        # Key pattern used in app.py
        pattern = "job:*"

        keys = client.keys(pattern)

        if keys:
            count = len(keys)
            client.delete(*keys)
            print(f"✅ Successfully removed {count} job(s) from Redis cache.")  # noqa: T201
        else:
            print("ℹ️ No cached jobs found in Redis.")  # noqa: T201

    except redis.ConnectionError:
        print("❌ Error: Could not connect to Redis. Is it running?")  # noqa: T201
        print("   Make sure Redis is installed and running on localhost:6379")  # noqa: T201
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error: {e}")  # noqa: T201


if __name__ == "__main__":
    clear_cache()
