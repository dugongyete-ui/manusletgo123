import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent
backend_path = project_root / "backend"
sys.path.insert(0, str(backend_path))

env_path = backend_path / ".env"
if env_path.exists():
    load_dotenv(str(env_path))

async def test_e2b_sandbox():
    print("--- Mengetes E2B Sandbox ---")
    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox
    
    try:
        print("Mencoba membuat sandbox E2B...")
        sandbox = await E2BSandbox.create()
        print(f"Berhasil membuat sandbox! ID: {sandbox.id}")
        print(f"Hostname: {sandbox.ip}")
        print(f"CDP URL: {sandbox.cdp_url}")
        
        print("Menghancurkan sandbox...")
        await sandbox.destroy()
        print("Sandbox berhasil dihancurkan.")
        return True
    except Exception as e:
        print(f"Gagal mengetes E2B Sandbox: {e}")
        return False

async def test_mongodb():
    print("\n--- Mengetes MongoDB ---")
    from motor.motor_asyncio import AsyncIOMotorClient
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DATABASE", "manus")
    
    if not uri:
        print("MONGODB_URI tidak dikonfigurasi — skip")
        return None
    
    try:
        client = AsyncIOMotorClient(uri)
        db = client[db_name]
        await db.command("ping")
        print(f"Berhasil terhubung ke MongoDB: {db_name}")
        return True
    except Exception as e:
        print(f"Gagal terhubung ke MongoDB: {e}")
        return False

async def test_redis():
    print("\n--- Mengetes Redis ---")
    import redis.asyncio as redis
    host = os.getenv("REDIS_HOST")
    port_str = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD")
    
    if not host:
        print("REDIS_HOST tidak dikonfigurasi — skip")
        return None
    
    try:
        r = redis.Redis(host=host, port=int(port_str), password=password, decode_responses=True)
        await r.ping()
        print(f"Berhasil terhubung ke Redis: {host}:{port_str}")
        return True
    except Exception as e:
        print(f"Gagal terhubung ke Redis: {e}")
        return False

async def main():
    e2b_ok = await test_e2b_sandbox()
    mongo_ok = await test_mongodb()
    redis_ok = await test_redis()
    
    print("\n--- Ringkasan Hasil ---")
    print(f"E2B Sandbox: {'OK' if e2b_ok else 'FAILED' if e2b_ok is False else 'SKIP'}")
    print(f"MongoDB: {'OK' if mongo_ok else 'FAILED' if mongo_ok is False else 'SKIP'}")
    print(f"Redis: {'OK' if redis_ok else 'FAILED' if redis_ok is False else 'SKIP'}")

if __name__ == "__main__":
    asyncio.run(main())
